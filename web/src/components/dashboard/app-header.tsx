import Image from "next/image";
import Link from "next/link";

/** The app's one bar: the KSE logo top-left, as the brand requires, and the product name. */
export function AppHeader() {
  return (
    <header className="border-b bg-background">
      <div className="flex h-16 items-center gap-3 px-4">
        <Link href="/" aria-label="KSE Notes" className="flex items-center gap-3 rounded-sm">
          <Image
            src="/kse-logo-black.svg"
            alt=""
            width={112}
            height={28}
            unoptimized
            priority
          />
          <span className="border-l pl-3 text-lg font-medium">Notes</span>
        </Link>
      </div>
    </header>
  );
}
