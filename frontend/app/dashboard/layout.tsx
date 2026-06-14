import { Sidebar } from "@/components/sidebar";
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen flex bg-bg">
       <Sidebar />
      
      <main className="flex-1 p-8 overflow-auto">{children}</main>
    </div>
  );
}