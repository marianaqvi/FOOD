import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FOOD / Sheep habitat control room",
  description: "Local preview of the two-sheep reception habitat",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
