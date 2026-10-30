import type { Metadata } from "next";
import { Sidebar } from "@/components/Sidebar";
import { StaticGate } from "@/components/StaticGate";
import "./globals.css";

export const metadata: Metadata = {
  title: "WETCOR AI",
  description: "Experimental intelligence platform for surface-wettability analysis, electrochemical corrosion characterisation and ML-assisted corrosion prediction.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-accent focus:px-3 focus:py-1 focus:text-accent-ink">
          Skip to content
        </a>
        <div className="flex">
          <Sidebar />
          <main id="main" className="min-w-0 flex-1 px-6 py-6 max-sm:px-4">
            <div className="mx-auto max-w-[1440px]"><StaticGate>{children}</StaticGate></div>
          </main>
        </div>
      </body>
    </html>
  );
}
