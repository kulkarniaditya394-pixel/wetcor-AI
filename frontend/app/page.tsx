import { redirect } from "next/navigation";

export default function Home() {
  redirect("/dashboard"); // static-demo mode redirects "/" to /showcase in next.config.ts
}
