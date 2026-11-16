"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { ApiError, type Me, updateMe } from "@/lib/api";

/** The teacher's name as the app shows it. Email comes from their Google account. */
export function AccountForm({ me }: { me: Me }) {
  const router = useRouter();
  const [firstName, setFirstName] = useState(me.first_name);
  const [lastName, setLastName] = useState(me.last_name);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const firstMissing = error !== null && !firstName.trim();
  const lastMissing = error !== null && !lastName.trim();
  const unchanged = firstName.trim() === me.first_name && lastName.trim() === me.last_name;

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!firstName.trim() || !lastName.trim()) {
      setError("Enter both your first and last name.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const saved = await updateMe({ first_name: firstName.trim(), last_name: lastName.trim() });
      setFirstName(saved.first_name);
      setLastName(saved.last_name);
      toast.success("Account saved");
      // The header shows the name: render it again from the server.
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="w-full max-w-lg">
      <form onSubmit={save} noValidate className="flex flex-col gap-6">
        <CardHeader>
          <CardTitle className="text-xl">Account details</CardTitle>
          <CardDescription>Your name as students and colleagues see it.</CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field data-invalid={firstMissing || undefined}>
              <FieldLabel htmlFor="first-name">First name</FieldLabel>
              <Input
                id="first-name"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                maxLength={100}
                autoComplete="given-name"
                aria-invalid={firstMissing || undefined}
                required
              />
            </Field>
            <Field data-invalid={lastMissing || undefined}>
              <FieldLabel htmlFor="last-name">Last name</FieldLabel>
              <Input
                id="last-name"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                maxLength={100}
                autoComplete="family-name"
                aria-invalid={lastMissing || undefined}
                required
              />
            </Field>
            <Field data-disabled>
              <FieldLabel htmlFor="email">Email</FieldLabel>
              <Input id="email" value={me.email} disabled readOnly />
              <FieldDescription>From your KSE Google account.</FieldDescription>
            </Field>
            {error && <FieldError>{error}</FieldError>}
          </FieldGroup>
        </CardContent>
        <CardFooter>
          <Button type="submit" disabled={saving || unchanged}>
            {saving && <Spinner data-icon="inline-start" />}
            Save
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}
