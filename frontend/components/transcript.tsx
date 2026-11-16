"use client";
import { useEffect, useRef, useState } from "react";
export type TranscriptMessage = {id:string;speaker:"customer"|"agent";text:string;timestamp:number};
const label = (speaker:TranscriptMessage["speaker"]) => speaker === "customer" ? "Siz" : "Freya Asistan";
export default function Transcript({messages,active}:{messages:TranscriptMessage[];active:boolean}) {
  const scrollRef=useRef<HTMLDivElement>(null);
  const followRef=useRef(true);
  const [status,setStatus]=useState("");
  useEffect(()=>{if(followRef.current && scrollRef.current)scrollRef.current.scrollTop=scrollRef.current.scrollHeight;},[messages]);
  useEffect(()=>{if(!status)return;const timer=setTimeout(()=>setStatus(""),2500);return()=>clearTimeout(timer);},[status]);
  async function copy(text:string){try{await navigator.clipboard.writeText(text);setStatus("Kopyalandı.");}catch{setStatus("Kopyalanamadı. Metni seçerek kopyalayabilirsiniz.");}}
  return <section className="conversation" aria-label="Görüşme dökümü">
    <div className="conversation-header"><div><h3>Görüşme dökümü</h3><span>{active?"Canlı konuşma":"Son görüşme"} · {messages.length} mesaj</span></div><button className="copy-button" disabled={!messages.length} onClick={()=>void copy(messages.map(m=>`${label(m.speaker)}: ${m.text}`).join("\n\n"))}>Tümünü kopyala</button></div>
    <div className="conversation-messages" ref={scrollRef} role="log" aria-label="Müşteri ve asistan mesajları" aria-live="off" tabIndex={0} onScroll={()=>{const el=scrollRef.current;if(el)followRef.current=el.scrollHeight-el.scrollTop-el.clientHeight<60;}}>
      {messages.length?messages.map(m=><article key={m.id} className={`message message-${m.speaker}`}><div className="message-meta"><strong>{label(m.speaker)}</strong><time dateTime={new Date(m.timestamp).toISOString()}>{new Date(m.timestamp).toLocaleTimeString("tr-TR",{hour:"2-digit",minute:"2-digit"})}</time></div><p>{m.text}</p><button className="message-copy" aria-label={`${label(m.speaker)} mesajını kopyala`} onClick={()=>void copy(m.text)}>Kopyala</button></article>):<p className="conversation-empty">Konuşmaya başladığınızda sizin ve asistanın mesajları burada görünecek.</p>}
    </div><p className="conversation-hint">Önceki mesajlar için yukarı kaydırın. Metinleri seçerek de kopyalayabilirsiniz.</p><span className="copy-status" role="status">{status}</span>
  </section>;
}
