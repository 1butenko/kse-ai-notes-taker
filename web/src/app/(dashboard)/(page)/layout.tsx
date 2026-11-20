/** The centred column most signed-in pages sit in. */
export default function PageLayout({ children }: LayoutProps<"/">) {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col px-4 py-8 sm:px-6 sm:py-10">
      {children}
    </main>
  );
}
