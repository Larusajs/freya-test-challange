"use client";
import { useEffect } from "react";
import { LiveKitRoom, RoomAudioRenderer, BarVisualizer, useVoiceAssistant, useConnectionState, useRoomContext, useTranscriptions, TrackToggle, DisconnectButton } from "@livekit/components-react";
import { ConnectionState, RoomEvent, Track } from "livekit-client";
import type { TranscriptMessage } from "./transcript";
function Controls({ onError, onTranscript }: {onError:(message:string)=>void;onTranscript:(messages:TranscriptMessage[])=>void}) {
  const { state, audioTrack } = useVoiceAssistant();
  const connection = useConnectionState();
  const room = useRoomContext();
  const transcriptions = useTranscriptions();
  useEffect(() => {
    if (!transcriptions.length) return;
    onTranscript(transcriptions.filter(t => t.text.trim()).map(t => ({
      id: `${t.participantInfo.identity}:${t.streamInfo.attributes?.["lk.segment_id"] || t.streamInfo.id}`,
      speaker: t.participantInfo.identity === room.localParticipant.identity ? "customer" : "agent",
      text: t.text,
      timestamp: t.streamInfo.timestamp,
    })));
  }, [transcriptions, room, onTranscript]);
  useEffect(() => {
    if (state !== "connecting" && state !== "initializing") return;
    const timer = setTimeout(() => {
      onError(connection === ConnectionState.Connected
        ? "Odaya bağlanıldı fakat sesli agent 45 saniyede hazır olmadı. LiveKit worker kaydını ve .local/logs/agent.log dosyasını kontrol edin."
        : "LiveKit oda bağlantısı 45 saniyede kurulamadı. Ağ bağlantısını ve LiveKit URL ayarını kontrol edin.");
      void room.disconnect();
    }, 45000);
    return () => clearTimeout(timer);
  }, [state, connection, room, onError]);
  useEffect(() => {
    const receiveError = (payload: Uint8Array, _participant: unknown, _kind: unknown, topic?: string) => {
      if (topic !== "freya.error") return;
      try {
        const data = JSON.parse(new TextDecoder().decode(payload));
        if (typeof data.message === "string") onError(data.message);
      } catch { /* Ignore malformed data packets. */ }
    };
    room.on(RoomEvent.DataReceived, receiveError);
    return () => { room.off(RoomEvent.DataReceived, receiveError); };
  }, [room, onError]);
  const waitingForAgent = connection === ConnectionState.Connected && state === "connecting";
  const labels: Record<string,string> = {disconnected:"Bağlantı kapalı", connecting:"Bağlanıyor", listening:"Seni dinliyor", thinking:"Düşünüyor", speaking:"Konuşuyor", initializing:"Agent hazırlanıyor"};
  return <>
    <div className="visualizer"><BarVisualizer state={state} trackRef={audioTrack} barCount={7}/></div>
    <p aria-live="polite">{waitingForAgent ? "Odaya bağlanıldı · Agent bekleniyor" : `${labels[state] || state} · ${connection}`}</p>
    <div className="actions"><TrackToggle source={Track.Source.Microphone}>Mikrofon</TrackToggle><DisconnectButton>Görüşmeyi bitir</DisconnectButton></div>
  </>;
}
export default function VoiceSession({session, onEnd, onError, onTranscript}: {session:{token:string;server_url:string};onEnd:()=>void;onError:(message:string)=>void;onTranscript:(messages:TranscriptMessage[])=>void}) {
  return <LiveKitRoom className="voice-session" token={session.token} serverUrl={session.server_url} connect audio video={false} onDisconnected={onEnd} onError={error=>onError(error.message)} onMediaDeviceFailure={()=>onError("Mikrofona erişilemiyor. Tarayıcı mikrofon iznini ve cihaz seçimini kontrol edin.")}>
    <RoomAudioRenderer/><Controls onError={onError} onTranscript={onTranscript}/>
  </LiveKitRoom>;
}
