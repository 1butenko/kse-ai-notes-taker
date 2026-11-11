import Image from "next/image";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";

/** The app's one bar: the KSE logo top-left, as the brand requires, and the product name. */
export function AppHeader() {
  return (
    <header className="border-b bg-background">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-3 px-4 sm:px-6">
        <Link href="/" aria-label="KSE Notes" className="flex items-center gap-3 rounded-sm">
          <Image
            src="/kse-logo-black.svg"
            alt=""
            width={96}
            height={33}
            className="block"
            unoptimized
            priority
          />
          <Badge className="h-8 px-4 text-lg font-medium">Notes</Badge>
        </Link>
      </div>
    </header>
  );
}
