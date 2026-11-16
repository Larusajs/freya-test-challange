"use client";
import { useCallback, useEffect, useState } from "react";
import VoiceSession from "../components/voice-session";
import Transcript, { type TranscriptMessage } from "../components/transcript";
type Customer = {id:string;name:string;phone:string;district:string;address_type:string;slot_id:string|null};
type Slot = {id:string;district:string;delivery_date:string;start:string;end:string;capacity:number;remaining:number};
type Call = {id:string;customer_id:string;verified:number;status:string};
type Callback = {id:string;name:string;phone:string;requested_at:string;status:"pending"|"completed"|"cancelled"};
type Dashboard = {customers:Customer[];slots:Slot[];calls:Call[];callbacks:Callback[]};
const dateLabel = (value:string) => new Date(`${value}T12:00:00`).toLocaleDateString("tr-TR",{day:"numeric",month:"long",weekday:"long"});
export default function Home() {
  const [data,setData]=useState<Dashboard|null>(null);
  const [messages,setMessages]=useState<TranscriptMessage[]>([]);
  const receiveTranscript=useCallback((incoming:TranscriptMessage[])=>{
    setMessages(previous=>{
      const merged=new Map(previous.map(message=>[message.id,message]));
      for(const message of incoming) merged.set(message.id,message);
      return Array.from(merged.values());
    });
  },[]);
  const [selected,setSelected]=useState("c1");
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const [session,setSession]=useState<{token:string;server_url:string}|null>(null);
  const refresh=useCallback(async()=>{
    try {const r=await fetch("/api/dashboard"); const d=await r.json(); if(!r.ok) throw new Error(d.detail); setData(d);}
    catch(e){setError(e instanceof Error?e.message:"Veri alınamadı.");}
  },[]);
  useEffect(()=>{void refresh(); const timer=setInterval(()=>void refresh(),5000); return ()=>clearInterval(timer);},[refresh]);
  async function start(){
    setBusy(true);setError("");
    try { const r=await fetch("/api/sessions",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({customer_id:selected})}); const d=await r.json(); if(!r.ok)throw new Error(d.detail);setMessages([]);setSession(d); }
    catch(e){setError(e instanceof Error?e.message:"Görüşme başlatılamadı.");}finally{setBusy(false);}
  }
  async function resolveCallback(id:string,status:"completed"|"cancelled") {
    setBusy(true);setError("");
    try {
      const r=await fetch(`/api/callbacks/${id}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({status})});
      const d=await r.json();if(!r.ok)throw new Error(d.detail);await refresh();
    } catch(e){setError(e instanceof Error?e.message:"Talep güncellenemedi.");}finally{setBusy(false);}
  }
  const customer=data?.customers.find(c=>c.id===selected);
  return <main>
    <header><a className="brand" href="/">✦ freya<span>delivery studio</span></a><span className="badge">LOCAL DEMO · v0.1</span></header>
    <section className="intro"><p className="eyebrow">AI-NATIVE BANKING / OPERATIONS</p><h1>Bir konuşmayla,<br/><em>yeniden kapında.</em></h1><p>Ulaşılamayan kart sahipleri için sesli teslimat planlama.<br/>Gerçek müsaitlik, açık onay, güvenilir rezervasyon.</p></section>
    <div className="stats"><div><b>{data?.customers.length ?? "—"}</b><span>Müşteri</span></div><div><b>{data?.slots.reduce((n,s)=>n+s.remaining,0) ?? "—"}</b><span>Kalan kurye yeri</span></div><div><b>{data?.customers.filter(c=>c.slot_id).length ?? "—"}</b><span>Planlanan teslimat</span></div></div>
    {error&&<p className="error" role="alert">{error}</p>}
    <div className="grid"><section className="panel"><p className="eyebrow">01 / SESLİ GÖRÜŞME</p><h2>Teslimat asistanıyla tanış.</h2><p className="muted">Bir demo müşterisi seç. Görüşmede o müşterinin doğum tarihiyle doğrulama yap.</p>
      <label htmlFor="customer">Demo müşterisi</label><select id="customer" value={selected} disabled={!!session||busy} onChange={e=>setSelected(e.target.value)}>{data?.customers.map(c=><option key={c.id} value={c.id}>{c.name} · {c.district}{c.slot_id?" · Planlandı":""}</option>)}</select>
      {customer&&<p className="muted">{customer.address_type} teslimatı · {customer.phone}</p>}
      {session?<VoiceSession session={session} onEnd={()=>{setSession(null);void refresh();}} onError={setError} onTranscript={receiveTranscript}/>:<div className="voice-idle"><div className="orb">✦</div><p>Asistan görüşmeye hazır</p><button onClick={start} disabled={!data||busy}>{busy?"Bağlantı hazırlanıyor…":"Sesli görüşmeyi başlat ↗"}</button></div>}
      <Transcript messages={messages} active={!!session}/>
      <p className="footnote">Tarayıcı mikrofonu kullanılır. Gerçek telefon araması başlatılmaz. Kart yalnız sahibine, kimlikle teslim edilir.</p>
    </section><section className="panel"><p className="eyebrow">02 / KURYE TAKVİMİ</p><h2>Bu haftanın rotası.</h2><p className="muted">Kapasite rezervasyon sırasında kontrol edilir.</p><div className="slots">{data?.slots.map(s=><div className="slot" key={s.id}><div><strong>{s.district}</strong><span>{dateLabel(s.delivery_date)}</span><span>{s.start} — {s.end}</span></div><span className={s.remaining?"pill":"pill full"}>{s.remaining?`${s.remaining} yer`:"Dolu"}</span></div>) ?? <p className="muted">API bağlantısı bekleniyor…</p>}</div></section></div>
    <section className="panel history"><p className="eyebrow">03 / GÖRÜŞME SONUÇLARI</p><h2>Operasyon görünümü.</h2>{data?.calls.length?<div className="call-list">{data.calls.map(c=><div className="call" key={c.id}><strong>{data.customers.find(x=>x.id===c.customer_id)?.name}</strong><span>{c.verified?"Doğrulandı":"Doğrulanmadı"}</span><span className="pill">{({started:"Başladı",booked:"Planlandı",declined:"Reddedildi",no_availability:"Uygun yer yok",needs_support:"Destek gerekli",verification_failed:"Doğrulama başarısız",callback_requested:"Geri aranma istendi",other_person:"Telefonu başkası açtı",incorrect_details:"Yanlış numara / kayıt bilgisi",existing_booking_confirmed:"Mevcut plan teyit edildi"} as Record<string,string>)[c.status]||c.status}</span></div>)}</div>:<p className="muted">Henüz görüşme yok. İlk görüşmeyi başlatarak akışı deneyebilirsin.</p>}</section>
    <section className="panel history"><p className="eyebrow">04 / GERİ ARANMA TALEPLERİ</p><h2>Geri aranma takibi.</h2><p className="muted">Saatler İstanbul saatidir. Talepler operasyon tarafından takip edilir; otomatik arama başlatılmaz. Tamamlandı seçeneğini geri arama yapıldıktan sonra kullan.</p>
      {data?.callbacks?.length?<div className="call-list">{data.callbacks.map(c=><div className="call" key={c.id}><div><strong>{c.name}</strong><p className="muted">{c.phone}<br/>{new Date(c.requested_at).toLocaleString("tr-TR",{timeZone:"Europe/Istanbul",dateStyle:"long",timeStyle:"short"})}</p></div><span className="pill">{{pending:"Bekliyor",completed:"Tamamlandı",cancelled:"İptal edildi"}[c.status]}</span>{c.status==="pending"&&<div className="actions"><button disabled={busy} onClick={()=>void resolveCallback(c.id,"completed")}>Tamamlandı</button><button disabled={busy} onClick={()=>void resolveCallback(c.id,"cancelled")}>İptal et</button></div>}</div>)}</div>:<p className="muted">Geri aranma talebi yok.</p>}
    </section>
    <footer>Freya case study · Next.js + Python + LiveKit<span>ElevenLabs voice / Gemini</span></footer>
  </main>;
}
