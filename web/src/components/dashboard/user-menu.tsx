"use client";

import Link from "next/link";
import { LogOutIcon, UserIcon } from "lucide-react";

import { signOutAction } from "@/app/actions";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type UserMenuProps = {
  name: string;
  email: string;
  avatarUrl: string | null;
};

function initials(name: string, email: string): string {
  const letters = name
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("");
  return (letters || email[0] || "?").slice(0, 2).toUpperCase();
}

/** The signed-in teacher: their account and signing out. */
export function UserMenu({ name, email, avatarUrl }: UserMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant="ghost" size="icon-lg" aria-label="Account menu" className="rounded-full" />}
      >
        <Avatar>
          {avatarUrl && <AvatarImage src={avatarUrl} alt="" referrerPolicy="no-referrer" />}
          <AvatarFallback>{initials(name, email)}</AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-56">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="flex flex-col gap-0.5">
            <span className="truncate font-medium text-foreground">{name || email}</span>
            {name && <span className="truncate font-normal">{email}</span>}
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem render={<Link href="/account" />}>
            <UserIcon />
            Account
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => signOutAction()}>
            <LogOutIcon />
            Sign out
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
