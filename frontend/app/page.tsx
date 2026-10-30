import { redirect } from "next/navigation";
import ShowcasePage from "./showcase/page";

export default function Home() {
  // Hosted static demo: "/" is the showcase itself (a redirect cannot be exported). Local app: overview.
  if (process.env.NEXT_PUBLIC_STATIC_DEMO === "1") return <ShowcasePage />;
  redirect("/dashboard");
}
