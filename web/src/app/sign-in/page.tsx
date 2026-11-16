import Image from "next/image";
import { redirect } from "next/navigation";
import { CircleAlertIcon } from "lucide-react";

import { signInWithGoogle } from "@/app/actions";
import { auth } from "@/auth";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const ERRORS: Record<string, { title: string; detail: string }> = {
  AccessDenied: {
    title: "Use your KSE Google account",
    detail: "Only KSE Workspace accounts can sign in. Choose your KSE account and try again.",
  },
};

const FALLBACK_ERROR = {
  title: "Couldn't sign you in",
  detail: "Something went wrong while signing in. Please try again.",
};

export default async function SignInPage({ searchParams }: PageProps<"/sign-in">) {
  const { error, callbackUrl } = await searchParams;
  const session = await auth();
  if (session?.user?.id) redirect("/");
  const problem = typeof error === "string" ? (ERRORS[error] ?? FALLBACK_ERROR) : null;

  return (
    <main className="flex flex-1 items-center justify-center px-4 py-16">
      <Card className="w-full max-w-sm">
        <CardHeader className="flex flex-col gap-4">
          <Image src="/kse-logo-full.svg" alt="Kyiv School of Economics" width={204} height={40} unoptimized priority />
          <CardTitle className="text-2xl">Sign in to KSE Notes</CardTitle>
          <CardDescription>Use your KSE Google account to see and create your courses.</CardDescription>
        </CardHeader>
        {problem && (
          <CardContent>
            <Alert variant="destructive">
              <CircleAlertIcon />
              <AlertTitle>{problem.title}</AlertTitle>
              <AlertDescription>{problem.detail}</AlertDescription>
            </Alert>
          </CardContent>
        )}
        <CardFooter>
          <form action={signInWithGoogle} className="w-full">
            <input type="hidden" name="callbackUrl" value={typeof callbackUrl === "string" ? callbackUrl : "/"} />
            <Button type="submit" size="lg" className="w-full">
              Sign in with Google
            </Button>
          </form>
        </CardFooter>
      </Card>
    </main>
  );
}
