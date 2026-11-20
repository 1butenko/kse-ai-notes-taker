import type { Metadata } from "next";
import { CircleAlertIcon } from "lucide-react";

import { AccountForm } from "@/components/account/account-form";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { getMe } from "@/lib/dal";

export const metadata: Metadata = { title: "Account · KSE Notes" };

export default async function Account() {
  const me = await getMe();
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-3xl">Account</h1>
      {me ? (
        <AccountForm me={me} />
      ) : (
        <Alert variant="destructive" className="max-w-lg">
          <CircleAlertIcon />
          <AlertTitle>Couldn&apos;t load your account</AlertTitle>
          <AlertDescription>The server is unreachable. Reload the page to try again.</AlertDescription>
        </Alert>
      )}
    </div>
  );
}
