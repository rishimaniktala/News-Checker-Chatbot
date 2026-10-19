import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "News Checker",
  description: "Check a claim against The Guardian and published fact-checks.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
