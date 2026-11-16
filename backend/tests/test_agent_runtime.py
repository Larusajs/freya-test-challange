import unittest
from unittest.mock import patch
from livekit.agents import APIStatusError, Agent
from app.agent import DeliveryAgent
from app.gemini_completion import GeminiCompletion


class ProviderFailureTest(unittest.IsolatedAsyncioTestCase):
    async def test_quota_failure_speaks_and_does_not_retry_next_user_turn(self):
        requests = []
        async def exhausted(*args):
            requests.append(True)
            raise APIStatusError('quota exceeded', status_code=429)
            yield
        with patch('app.agent.store.call_customer', return_value={'id':'c1','name':'Ayşe Kaya'}):
            agent = DeliveryAgent('test-call')
        with patch.object(GeminiCompletion, 'generate', exhausted), patch('app.agent.get_job_context', return_value=None):
            first = [chunk async for chunk in agent.llm_node(None, [], None)]
            second = [chunk async for chunk in agent.llm_node(None, [], None)]
        self.assertEqual(len(requests), 1)
        self.assertIn('kullanım sınırına', first[0])
        self.assertEqual(first, second)

    async def test_successful_turn_streams_normally(self):
        async def reply(*args):
            yield 'Doğum tarihinizi öğrenebilir miyim?'
        with patch('app.agent.store.call_customer', return_value={'id':'c1','name':'Ayşe Kaya'}):
            agent = DeliveryAgent('test-call')
        with patch.object(GeminiCompletion, 'generate', reply):
            chunks = [chunk async for chunk in agent.llm_node(None, [], None)]
        self.assertEqual(chunks, ['Doğum tarihinizi öğrenebilir miyim?'])

class GeminiResponseTest(unittest.IsolatedAsyncioTestCase):
    async def test_thoughts_are_not_spoken_and_signature_is_saved_for_tool_turn(self):
        import base64
        completion = GeminiCompletion()
        data = {'candidates':[{'content':{'parts':[
            {'thought':True, 'text':'private reasoning'},
            {'functionCall':{'id':'call-1','name':'verify_identity','args':{'birth_date':'1988-03-14'}},
             'thoughtSignature':base64.b64encode(b'signature').decode()},
            {'text':'Kontrol ediyorum.'},
        ]}}]}
        chunks = [chunk async for chunk in completion.chunks(data)]
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].delta.tool_calls[0].name, 'verify_identity')
        self.assertEqual(completion.thought_signatures['call-1'], b'signature')
        self.assertEqual(chunks[1].delta.content, 'Kontrol ediyorum.')

    async def test_empty_provider_response_is_an_explicit_error(self):
        from livekit.agents import APIStatusError
        for data in ({}, {'candidates':[{'content':{'parts':[]}}]}):
            with self.assertRaises(APIStatusError):
                _ = [chunk async for chunk in GeminiCompletion().chunks(data)]

class ToolContinuationTest(unittest.IsolatedAsyncioTestCase):
    async def test_verified_result_speaks_slots_without_calling_gemini(self):
        import json
        from livekit.agents import llm
        from unittest.mock import AsyncMock
        result = {'verified':True,'booking':None,'slots':[
            {'id':'s1','delivery_date':'2026-11-19','start':'09:00','end':'13:00','remaining':1},
        ]}
        context = llm.ChatContext()
        from livekit.agents.llm.utils import make_function_call_output
        output = make_function_call_output(
            fnc_call=llm.FunctionCall(name='verify_identity', call_id='call-1', arguments='{}'),
            output=result, exception=None,
        ).fnc_call_out
        context.items.append(output)
        with patch('app.agent.store.call_customer', return_value={'id':'c1','name':'Ayşe Kaya'}):
            agent = DeliveryAgent('test-call')
        with patch.object(agent._completion, 'generate', new=AsyncMock(side_effect=AssertionError('Gemini must not be called'))):
            chunks = [chunk async for chunk in agent.llm_node(context, [], None)]
        self.assertIn('Kimliğiniz doğrulandı', chunks[0])
        self.assertIn('19 Kasım 2026 Perşembe', chunks[0])
        self.assertIn('09:00 ile 13:00', chunks[0])

    async def test_failed_identity_never_announces_success_or_slots(self):
        from app.tool_replies import tool_reply
        reply = tool_reply('verify_identity', {'verified':False,'remaining_attempts':2})
        self.assertIn('tekrar', reply)
        self.assertNotIn('doğrulandı', reply)
        self.assertNotIn('teslimat zamanları', reply)

class BirthDateInputTest(unittest.TestCase):
    def test_unambiguous_dates(self):
        from app.birth_dates import parse_birth_date
        for value in ['14.03.1988.', '14 Mart 1988', 'Doğum tarihim 14 Mart 1988.', '1988-03-14']:
            self.assertEqual(parse_birth_date(value), '1988-03-14')
        for value in ['14.03.88', '31 Şubat 1988', 'müsait değilim', '14 Mart', 'başkasının doğum tarihi 14 Mart 1988']:
            self.assertIsNone(parse_birth_date(value))

class IdentityFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_acknowledgment_and_date_reach_real_sqlite_and_speak_options_without_llm(self):
        import tempfile
        from pathlib import Path
        from livekit.agents import llm
        from unittest.mock import AsyncMock
        from app import store
        from app.config import settings
        original = settings.database_path
        with tempfile.TemporaryDirectory() as directory:
            settings.database_path = str(Path(directory) / 'identity.sqlite3')
            try:
                store.initialize()
                call_id = store.create_call('c1')
                agent = DeliveryAgent(call_id)
                context = llm.ChatContext()
                context.add_message(role='user',content='Evet, buyurun.')
                with patch.object(agent._completion, 'generate', new=AsyncMock(side_effect=AssertionError('Unexpected LLM request'))):
                    first = [chunk async for chunk in agent.llm_node(context, [], None)]
                    self.assertIn('doğum tarihinizi',first[0])
                    context.add_message(role='assistant',content=first[0])
                    context.add_message(role='user',content='14.03.1988.')
                    second = [chunk async for chunk in agent.llm_node(context, [], None)]
                self.assertIn('Kimliğiniz doğrulandı', second[0])
                self.assertIn('Hangisi sizin için uygun', second[0])
                with store.connection() as db:
                    self.assertEqual(db.execute('SELECT verified FROM calls WHERE id=?',(call_id,)).fetchone()[0],1)
            finally:
                settings.database_path = original

class CompletedCallTest(unittest.IsolatedAsyncioTestCase):
    async def test_booking_disconnect_waits_until_final_speech_is_finished(self):
        from unittest.mock import Mock, AsyncMock
        with patch('app.agent.store.call_customer', return_value={'id':'c1','name':'Ayşe Kaya'}):
            agent = DeliveryAgent('test-call')
        context = Mock()
        job = Mock()
        job.delete_room = AsyncMock()
        booking = {'booking_id':'b1','slot_id':'s1','delivery_date':'2026-11-19','start':'09:00','end':'13:00'}
        with patch('app.agent.store.book', return_value=booking), patch('app.agent.get_job_context', return_value=job):
            result = await agent.reserve_delivery(context, 's1', True)
            self.assertEqual(result['booking_id'],'b1')
            job.delete_room.assert_not_called()
            context.disallow_interruptions.assert_called_once()
            callback = context.speech_handle.add_done_callback.call_args.args[0]
            callback(context.speech_handle)
            await agent._end_call_task
        job.delete_room.assert_awaited_once()
        context.session.shutdown.assert_called_once()
        job.shutdown.assert_called_once_with(reason='delivery_completed')

    async def test_failed_booking_keeps_call_open(self):
        from unittest.mock import Mock
        from app import store
        with patch('app.agent.store.call_customer', return_value={'id':'c1','name':'Ayşe Kaya'}):
            agent = DeliveryAgent('test-call')
        context = Mock()
        with patch('app.agent.store.book', side_effect=store.RuleError('Bu saat doldu.')):
            result = await agent.reserve_delivery(context, 's1', True)
        self.assertIn('error',result)
        context.speech_handle.add_done_callback.assert_not_called()
        context.session.input.set_audio_enabled.assert_not_called()

class WrongRecipientCallTest(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_recipient_is_persisted_and_disconnect_waits_for_goodbye(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import Mock, AsyncMock
        from app import store
        from app.config import settings
        from app.tool_replies import tool_reply
        original = settings.database_path
        with tempfile.TemporaryDirectory() as directory:
            settings.database_path = str(Path(directory) / 'wrong-recipient.sqlite3')
            try:
                store.initialize()
                for outcome in ('other_person', 'incorrect_details'):
                    call_id = store.create_call('c2')
                    agent = DeliveryAgent(call_id)
                    context = Mock()
                    job = Mock()
                    job.delete_room = AsyncMock()
                    with patch('app.agent.get_job_context', return_value=job):
                        result = await agent.confirm_recipient(context, outcome)
                        self.assertIn('İyi günler', tool_reply('confirm_recipient', result))
                        with store.connection() as db:
                            row = db.execute('SELECT * FROM calls WHERE id=?',(call_id,)).fetchone()
                            self.assertEqual(row['status'], outcome)
                            self.assertEqual(row['recipient_status'], outcome)
                            self.assertFalse(row['verified'])
                        job.delete_room.assert_not_called()
                        callback = context.speech_handle.add_done_callback.call_args.args[0]
                        callback(context.speech_handle)
                        await agent._end_call_task
                    job.delete_room.assert_awaited_once()
                    job.shutdown.assert_called_once_with(reason=outcome)
            finally:
                settings.database_path = original

class ExplicitWrongNameTest(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_wrong_name_calls_recipient_tool_without_gemini(self):
        import json
        from livekit.agents import llm
        from unittest.mock import AsyncMock
        with patch('app.agent.store.call_customer', return_value={'id':'c2','name':'Mehmet Demir'}):
            agent = DeliveryAgent('test-call')
        context = llm.ChatContext()
        context.add_message(role='user', content='Yok, hayır. Benim adım Enes.')
        with patch.object(agent._completion, 'generate', new=AsyncMock(side_effect=AssertionError('Unexpected LLM request'))):
            chunks = [chunk async for chunk in agent.llm_node(context, [], None)]
        tool = chunks[0].delta.tool_calls[0]
        self.assertEqual(tool.name,'confirm_recipient')
        self.assertEqual(json.loads(tool.arguments),{'recipient_status':'incorrect_details'})

class OptOutCallTest(unittest.IsolatedAsyncioTestCase):
    async def test_opt_out_is_persisted_and_goodbye_finishes_before_disconnect(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import Mock, AsyncMock
        from app import store
        from app.config import settings
        from app.tool_replies import tool_reply
        original = settings.database_path
        with tempfile.TemporaryDirectory() as directory:
            settings.database_path = str(Path(directory) / 'opt-out.sqlite3')
            try:
                store.initialize()
                call = store.create_call('c1')
                store.confirm_recipient(call, 'self')
                agent = DeliveryAgent(call)
                context = Mock()
                job = Mock()
                job.delete_room = AsyncMock()
                with patch('app.agent.get_job_context', return_value=job):
                    result = await agent.opt_out_calls(context, True)
                    self.assertIn('tercihinizi kaydettim', tool_reply('opt_out_calls', result))
                    self.assertEqual(store.dashboard()['customers'][0]['do_not_call'], 1)
                    job.delete_room.assert_not_called()
                    context.speech_handle.add_done_callback.call_args.args[0](context.speech_handle)
                    await agent._end_call_task
                job.delete_room.assert_awaited_once()
                job.shutdown.assert_called_once_with(reason='do_not_call')
            finally:
                settings.database_path = original

class CallbackCallEndTest(unittest.IsolatedAsyncioTestCase):
    async def test_saved_callback_closes_after_goodbye_only(self):
        from unittest.mock import Mock, AsyncMock
        from app.tool_replies import tool_reply
        with patch('app.agent.store.call_customer', return_value={'id':'c3','name':'Zeynep Arslan'}):
            agent = DeliveryAgent('test-call')
        context = Mock()
        job = Mock()
        job.delete_room = AsyncMock()
        saved = {'callback_id':'cb1','requested_at':'2026-11-17T20:00:00+03:00','status':'pending'}
        with patch('app.agent.store.request_callback', return_value=saved), patch('app.agent.get_job_context', return_value=job):
            result = await agent.request_callback(context, saved['requested_at'], True)
            self.assertIn('iyi günler',tool_reply('request_callback',result))
            job.delete_room.assert_not_called()
            context.speech_handle.add_done_callback.call_args.args[0](context.speech_handle)
            await agent._end_call_task
        job.delete_room.assert_awaited_once()
        job.shutdown.assert_called_once_with(reason='callback_requested')

    async def test_failed_callback_does_not_close_the_call(self):
        from unittest.mock import Mock
        from app import store
        with patch('app.agent.store.call_customer', return_value={'id':'c3','name':'Zeynep Arslan'}):
            agent = DeliveryAgent('test-call')
        context = Mock()
        with patch('app.agent.store.request_callback', side_effect=store.RuleError('Geri aranma zamanı gelecekte olmalı.')):
            result = await agent.request_callback(context, '2000-01-01T20:00:00+03:00',True)
        self.assertIn('error', result)
        context.speech_handle.add_done_callback.assert_not_called()
