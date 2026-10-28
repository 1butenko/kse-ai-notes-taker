import type { Metadata } from "next";
import { Geist_Mono } from "next/font/google";
import localFont from "next/font/local";

import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

import "./globals.css";

// KSE Sans from the KSE design system: Latin and Ukrainian Cyrillic.
const kseSans = localFont({
  variable: "--font-kse-sans",
  display: "swap",
  src: [
    { path: "./fonts/KSE-SansRegular.woff2", weight: "400", style: "normal" },
    { path: "./fonts/KSE-SansMedium.woff2", weight: "500", style: "normal" },
    { path: "./fonts/KSE-SansBold.woff2", weight: "700", style: "normal" },
  ],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "KSE Notes",
  description: "Turn a course syllabus and its readings into lecture notes.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${kseSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <TooltipProvider>{children}</TooltipProvider>
        <Toaster theme="light" richColors position="bottom-right" />
      </body>
    </html>
  );
}
