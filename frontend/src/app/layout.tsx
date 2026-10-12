import type { Metadata } from "next";
import {
  Instrument_Sans,
  Spline_Sans_Mono,
  Vazirmatn,
} from "next/font/google";
import localFont from "next/font/local";
import "./globals.css";
import "@/custom/theme/tokens.css";
import "katex/dist/katex.min.css";
import { Toaster } from "@/components/ui/sonner";
import { QueryProvider } from "@/components/providers/QueryProvider";
import { ThemeProvider } from "@/components/providers/ThemeProvider";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { ConnectionGuard } from "@/components/common/ConnectionGuard";
import { themeScript } from "@/lib/theme-script";
import { I18nProvider } from "@/components/providers/I18nProvider";

const instrumentSans = Instrument_Sans({
  subsets: ["latin"],
  variable: "--font-instrument-sans",
});

const bricolageGrotesque = localFont({
  // Self-hosted: Turbopack dev cannot resolve next/font/google's
  // parameterized /l/font?kit=&skey= URLs for this family (see fonts/OFL.txt
  // for license). Same bytes Google serves for latin 600/700; variable name
  // and weights unchanged so all existing CSS keeps working.
  src: [
    { path: "./fonts/bricolage-grotesque-latin.woff2", weight: "600" },
    { path: "./fonts/bricolage-grotesque-latin.woff2", weight: "700" },
  ],
  variable: "--font-bricolage",
  display: "swap",
});

const splineSansMono = Spline_Sans_Mono({
  subsets: ["latin"],
  variable: "--font-spline-mono",
});

// Persian-capable font. Only applied when <html lang="fa"> (see
// custom/theme/tokens.css); English keeps the existing font stack.
const vazirmatn = Vazirmatn({
  subsets: ["arabic", "latin"],
  variable: "--font-vazirmatn",
});

export const metadata: Metadata = {
  title: "Maintenance AI Agent",
  description: "Privacy-focused research and knowledge management",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body
        className={`${instrumentSans.variable} ${bricolageGrotesque.variable} ${splineSansMono.variable} ${vazirmatn.variable} font-sans`}
      >
        <ErrorBoundary>
          <ThemeProvider>
            <QueryProvider>
              <I18nProvider>
                <ConnectionGuard>
                  {children}
                  <Toaster />
                </ConnectionGuard>
              </I18nProvider>
            </QueryProvider>
          </ThemeProvider>
        </ErrorBoundary>
      </body>
    </html>
  );
}
