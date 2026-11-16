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
