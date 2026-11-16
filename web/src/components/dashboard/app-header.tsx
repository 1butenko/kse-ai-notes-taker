import Image from "next/image";
import Link from "next/link";

import { UserMenu } from "@/components/dashboard/user-menu";
import { Badge } from "@/components/ui/badge";
import { getMe, verifySession } from "@/lib/dal";

/** The app's one bar: the KSE logo top-left, as the brand requires, the product name, and the
 * signed-in teacher's menu. */
export async function AppHeader() {
  const { user } = await verifySession();
  const me = await getMe();
  const name = me ? `${me.first_name} ${me.last_name}`.trim() : (user.name ?? "");
  const email = me?.email ?? user.email ?? "";

  return (
    <header className="border-b bg-background">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-3 px-4 sm:px-6">
        <Link href="/" aria-label="KSE Notes" className="flex items-center gap-3 rounded-sm">
          <Image
            src="/kse-logo.svg"
            alt=""
            width={96}
            height={33}
            className="block"
            unoptimized
            priority
          />
          <Badge className="h-8 px-4 text-lg font-medium">Notes</Badge>
        </Link>
        <div className="ml-auto">
          <UserMenu name={name} email={email} avatarUrl={me?.avatar_url ?? user.image ?? null} />
        </div>
      </div>
    </header>
  );
}
