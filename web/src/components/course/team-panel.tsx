"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  CircleAlertIcon,
  CrownIcon,
  EllipsisIcon,
  HistoryIcon,
  UserMinusIcon,
  UserPlusIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "@/components/ui/item";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import {
  ApiError,
  addTeamMember,
  getCourseActivity,
  getTeam,
  removeTeamMember,
  setLecturer,
  type CourseEvent,
  type CourseRole,
  type Team,
  type TeamMember,
} from "@/lib/api";

function errorMessage(err: unknown) {
  return err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.";
}

const ROLE_LABEL: Record<CourseRole, string> = { lecturer: "Lecturer", ta: "TA", admin: "Admin" };

/** The caller's or a member's role on a course. */
export function RoleBadge({ role }: { role: CourseRole }) {
  return (
    <Badge variant={role === "lecturer" ? "secondary" : "outline"}>{ROLE_LABEL[role]}</Badge>
  );
}

export type TeamState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; team: Team };

/** The course's team; `reload` after a change made elsewhere, `set` with a team a change returned. */
export function useTeam(course: string) {
  const [state, setState] = useState<TeamState>({ kind: "loading" });

  const reload = useCallback(() => {
    getTeam(course).then(
      (team) => setState({ kind: "ready", team }),
      (err) => setState({ kind: "error", message: errorMessage(err) }),
    );
  }, [course]);

  useEffect(() => {
    let active = true;
    getTeam(course).then(
      (team) => active && setState({ kind: "ready", team }),
      (err) => active && setState({ kind: "error", message: errorMessage(err) }),
    );
    return () => {
      active = false;
    };
  }, [course]);

  const set = useCallback((team: Team) => setState({ kind: "ready", team }), []);
  return { state, reload, set };
}

function initials(name: string, email: string): string {
  const letters = name
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("");
  return (letters || email[0] || "?").slice(0, 2).toUpperCase();
}

type Pending = { kind: "remove" | "lecturer"; member: TeamMember };

type TeamPanelProps = {
  course: string;
  state: TeamState;
  onTeam: (team: Team) => void;
  onRetry: () => void;
};

/** The Team tab: who is on the course, and what they did. */
export function TeamPanel({ course, state, onTeam, onRetry }: TeamPanelProps) {
  // Bumped after each change, so the activity shows it.
  const [changes, setChanges] = useState(0);

  if (state.kind === "loading") {
    return (
      <div className="grid gap-6 lg:grid-cols-2">
        <Skeleton className="h-72 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <Alert variant="destructive">
        <CircleAlertIcon />
        <AlertTitle>Couldn&apos;t load the team</AlertTitle>
        <AlertDescription className="flex flex-col items-start gap-2">
          {state.message}
          <Button size="sm" variant="outline" onClick={onRetry}>
            Try again
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
      <MembersCard
        course={course}
        team={state.team}
        onTeam={(team) => {
          onTeam(team);
          setChanges((count) => count + 1);
        }}
      />
      <ActivityCard course={course} changes={changes} />
    </div>
  );
}

function MembersCard({
  course,
  team,
  onTeam,
}: {
  course: string;
  team: Team;
  onTeam: (team: Team) => void;
}) {
  const canManage = team.my_role !== "ta";
  const lecturer = team.members.find((member) => member.role === "lecturer");
  const [email, setEmail] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [confirming, setConfirming] = useState(false);

  const add = async (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim()) return;
    setAdding(true);
    setAddError(null);
    try {
      onTeam(await addTeamMember(course, email.trim()));
      toast.success(`${email.trim()} can now work on this course`);
      setEmail("");
    } catch (err) {
      setAddError(errorMessage(err));
    } finally {
      setAdding(false);
    }
  };

  const confirm = async () => {
    if (!pending) return;
    setConfirming(true);
    try {
      const { kind, member } = pending;
      onTeam(
        kind === "remove"
          ? await removeTeamMember(course, member.email)
          : await setLecturer(course, member.email),
      );
      toast.success(
        kind === "remove"
          ? `${member.email} was removed from the course`
          : `${member.name || member.email} is now the lecturer`,
      );
      setPending(null);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setConfirming(false);
    }
  };

  const pendingName = pending ? pending.member.name || pending.member.email : "";

  return (
    <Card>
      <CardHeader>
        <CardTitle>Members</CardTitle>
        <CardDescription>
          {canManage
            ? "The lecturer and TAs work on the course together. Only the lecturer and admins change who is on it."
            : "Everyone here works on the course. Only the lecturer or an admin can change who is on it."}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {!lecturer && (
          <Alert>
            <CircleAlertIcon />
            <AlertTitle>This course has no lecturer</AlertTitle>
            <AlertDescription>
              {canManage
                ? "Add the lecturer as a TA, then choose Make lecturer next to them."
                : "An admin can give it one."}
            </AlertDescription>
          </Alert>
        )}
        <ItemGroup className="gap-2">
          {team.members.map((member) => (
            <Item key={member.email} variant="outline" size="sm">
              <ItemMedia>
                <Avatar>
                  {member.avatar_url && (
                    <AvatarImage src={member.avatar_url} alt="" referrerPolicy="no-referrer" />
                  )}
                  <AvatarFallback>{initials(member.name, member.email)}</AvatarFallback>
                </Avatar>
              </ItemMedia>
              <ItemContent className="min-w-0">
                <ItemTitle className="flex-wrap">
                  <span className="truncate">{member.name || member.email}</span>
                  <RoleBadge role={member.role} />
                </ItemTitle>
                <ItemDescription className="truncate">
                  {member.signed_in
                    ? member.name && member.email
                    : `${member.name ? `${member.email} · ` : ""}Hasn't signed in yet`}
                </ItemDescription>
              </ItemContent>
              {canManage && member.role === "ta" && (
                <ItemActions>
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      render={
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Actions for ${member.name || member.email}`}
                        />
                      }
                    >
                      <EllipsisIcon />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="min-w-48">
                      <DropdownMenuGroup>
                        <DropdownMenuItem onClick={() => setPending({ kind: "lecturer", member })}>
                          <CrownIcon />
                          Make lecturer
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          variant="destructive"
                          onClick={() => setPending({ kind: "remove", member })}
                        >
                          <UserMinusIcon />
                          Remove from course
                        </DropdownMenuItem>
                      </DropdownMenuGroup>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </ItemActions>
              )}
            </Item>
          ))}
        </ItemGroup>
      </CardContent>
      {canManage && (
        <CardFooter>
          <form onSubmit={add} className="w-full">
            <Field data-invalid={addError ? true : undefined}>
              <FieldLabel htmlFor="team-email">Add a TA</FieldLabel>
              <div className="flex gap-2">
                <Input
                  id="team-email"
                  type="email"
                  placeholder="name@kse.org.ua"
                  autoComplete="off"
                  value={email}
                  aria-invalid={addError ? true : undefined}
                  onChange={(event) => {
                    setEmail(event.target.value);
                    setAddError(null);
                  }}
                />
                <Button type="submit" disabled={adding || !email.trim()}>
                  {adding ? <Spinner data-icon="inline-start" /> : <UserPlusIcon data-icon="inline-start" />}
                  Add
                </Button>
              </div>
              {addError ? (
                <FieldError>{addError}</FieldError>
              ) : (
                <FieldDescription>
                  Their KSE email. They see the course the next time they sign in; no email is
                  sent, so let them know.
                </FieldDescription>
              )}
            </Field>
          </form>
        </CardFooter>
      )}

      <Dialog
        open={pending !== null}
        onOpenChange={(open) => !open && !confirming && setPending(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {pending?.kind === "remove"
                ? `Remove ${pendingName}?`
                : `Make ${pendingName} the lecturer?`}
            </DialogTitle>
            <DialogDescription>
              {pending?.kind === "remove"
                ? "They lose access to the course. What they already did stays in the activity."
                : team.my_role === "lecturer"
                  ? "They will manage the team and can start the course over. You stay on as a TA and can no longer change who is on the course."
                  : lecturer
                    ? `They will manage the team and can start the course over. ${lecturer.name || lecturer.email} stays on as a TA.`
                    : "They will manage the team and can start the course over."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>Cancel</DialogClose>
            <Button
              variant={pending?.kind === "remove" ? "destructive" : "default"}
              disabled={confirming}
              onClick={confirm}
            >
              {confirming && <Spinner data-icon="inline-start" />}
              {pending?.kind === "remove" ? "Remove" : "Make lecturer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

const when = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" });

function files(details: Record<string, unknown>): string[] {
  return Array.isArray(details.files) ? details.files.map(String) : [];
}

/** What an event did, after its actor's name. */
export function describeEvent(event: CourseEvent): string {
  const d = event.details;
  const names = files(d);
  switch (event.kind) {
    case "material_uploaded": {
      const what =
        d.category === "syllabus"
          ? names.length === 1 ? "a syllabus" : "syllabus files"
          : names.length === 1 ? "a reading" : `${names.length} readings`;
      return `added ${what}: ${names.join(", ")}`;
    }
    case "material_deleted":
      return `deleted ${names.join(", ") || "a file"}`;
    case "moodle_synced":
      return "synced materials from Moodle";
    case "notes_generated":
      return `generated notes for ${typeof d.label === "string" && d.label ? d.label : "a lecture"}`;
    case "readings_approved":
      return "approved the readings";
    case "readings_approval_revoked":
      return "withdrew the readings approval";
    case "member_added":
      return `added ${String(d.email)} as a TA`;
    case "member_removed":
      return `removed ${String(d.email)} from the course`;
    case "lecturer_changed":
      return `made ${String(d.email)} the lecturer`;
    case "course_started_over":
      return "started the course over";
    default:
      return event.kind;
  }
}

type ActivityState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; events: CourseEvent[] };

function ActivityCard({ course, changes }: { course: string; changes: number }) {
  const [state, setState] = useState<ActivityState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    getCourseActivity(course).then(
      (events) => active && setState({ kind: "ready", events }),
      (err) => active && setState({ kind: "error", message: errorMessage(err) }),
    );
    return () => {
      active = false;
    };
  }, [course, changes, attempt]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Activity</CardTitle>
        <CardDescription>Who added materials, generated notes and changed the team.</CardDescription>
      </CardHeader>
      <CardContent>
        {state.kind === "loading" && (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 4 }, (_, index) => (
              <Skeleton key={index} className="h-12 w-full" />
            ))}
          </div>
        )}
        {state.kind === "error" && (
          <Alert variant="destructive">
            <CircleAlertIcon />
            <AlertTitle>Couldn&apos;t load the activity</AlertTitle>
            <AlertDescription className="flex flex-col items-start gap-2">
              {state.message}
              <Button size="sm" variant="outline" onClick={() => setAttempt((n) => n + 1)}>
                Try again
              </Button>
            </AlertDescription>
          </Alert>
        )}
        {state.kind === "ready" && state.events.length === 0 && (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <HistoryIcon />
              </EmptyMedia>
              <EmptyTitle>Nothing yet</EmptyTitle>
              <EmptyDescription>Uploads, notes and team changes show up here.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
        {state.kind === "ready" && state.events.length > 0 && (
          <ItemGroup>
            {state.events.map((event) => (
              <Item key={event.id} size="xs">
                <ItemContent className="min-w-0">
                  <p className="text-sm">
                    {/* Runs from before the activity log, and the worker's own syncs, have no actor. */}
                    <span className="font-medium">
                      {event.actor_name || event.actor_email || "Someone"}
                    </span>{" "}
                    {describeEvent(event)}
                  </p>
                  <ItemDescription>
                    <time dateTime={event.at}>{when.format(new Date(event.at))}</time>
                  </ItemDescription>
                </ItemContent>
              </Item>
            ))}
          </ItemGroup>
        )}
      </CardContent>
    </Card>
  );
}
