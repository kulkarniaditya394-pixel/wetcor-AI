import type { ReactNode } from "react";

// Required by `output: "export"` (hosted static demo). One placeholder id; the live app still renders any id on demand.
export function generateStaticParams() {
  return [{ id: "0" }];
}

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
