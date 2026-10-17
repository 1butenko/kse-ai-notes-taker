import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";

export default function Dashboard() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-4 py-10 sm:px-6">
      <Empty>
        <EmptyHeader>
          <EmptyTitle>Notes generation is being rebuilt</EmptyTitle>
          <EmptyDescription>
            The new generation engine lives in api/app/engine. The UI for it comes next.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    </div>
  );
}
