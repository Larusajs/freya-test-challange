import type { Metadata } from "next";
import "@livekit/components-styles";
import "./globals.css";
export const metadata: Metadata = { title: "Freya · Teslimat Asistanı", description: "Sesli kart teslimat planlama demosu" };
export default function Layout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="tr"><body>{children}</body></html>;
}
