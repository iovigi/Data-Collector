import React, { Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Outlet, RouterProvider, useRouteError } from "react-router";
import "@/styles/globals.css";
import { Providers } from "@/components/providers";
import { Link } from "@/lib/router";

const HomeRedirectPage = lazy(() => import("@/app/page"));
const LoginPage = lazy(() => import("@/app/(auth)/login/page"));
const CreateWorkspacePage = lazy(() => import("@/app/onboarding/create-workspace/page"));
const DeveloperApiPage = lazy(() => import("@/app/developer/api/page"));
const OverviewPage = lazy(() => import("@/app/w/[workspaceId]/overview/page"));
const ProjectsPage = lazy(() => import("@/app/w/[workspaceId]/projects/page"));
const ProjectDetailPage = lazy(() => import("@/app/w/[workspaceId]/projects/[projectId]/page"));
const CollectionsPage = lazy(() => import("@/app/w/[workspaceId]/collections/page"));
const CollectionDataPage = lazy(
  () => import("@/app/w/[workspaceId]/collections/[collectionId]/data/page")
);
const CollectionQueriesPage = lazy(
  () => import("@/app/w/[workspaceId]/collections/[collectionId]/queries/page")
);
const CollectionSchemaPage = lazy(
  () => import("@/app/w/[workspaceId]/collections/[collectionId]/schema/page")
);
const JobsPage = lazy(() => import("@/app/w/[workspaceId]/jobs/page"));
const KeysPage = lazy(() => import("@/app/w/[workspaceId]/keys/page"));
const McpPage = lazy(() => import("@/app/w/[workspaceId]/mcp/page"));
const WebhooksPage = lazy(() => import("@/app/w/[workspaceId]/webhooks/page"));
const AuditPage = lazy(() => import("@/app/w/[workspaceId]/audit/page"));
const AnalyticsPage = lazy(() => import("@/app/w/[workspaceId]/analytics/page"));
const MembersPage = lazy(() => import("@/app/w/[workspaceId]/members/page"));
const SettingsPage = lazy(() => import("@/app/w/[workspaceId]/settings/page"));

function PageFallback() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[hsl(var(--surface))] text-sm text-[hsl(var(--muted-foreground))]">
      Loading...
    </div>
  );
}

function RootLayout() {
  return (
    <Providers>
      <Suspense fallback={<PageFallback />}>
        <Outlet />
      </Suspense>
    </Providers>
  );
}

function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-[hsl(var(--surface))] p-6 text-center">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <p className="text-sm text-[hsl(var(--muted-foreground))]">
        The page you requested does not exist.
      </p>
      <Link href="/" className="text-sm font-medium text-[hsl(var(--primary))] underline">
        Go to dashboard
      </Link>
    </div>
  );
}

function RouteErrorPage() {
  const error = useRouteError();
  if (import.meta.env.DEV) console.error(error);
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-[hsl(var(--surface))] p-6 text-center">
      <h1 className="text-xl font-semibold">Something went wrong</h1>
      <p className="text-sm text-[hsl(var(--muted-foreground))]">
        Reload the page. If the problem persists, contact your administrator.
      </p>
      <a href="/" className="text-sm font-medium text-[hsl(var(--primary))] underline">
        Go to dashboard
      </a>
    </div>
  );
}

const W = "/w/:workspaceId";

const router = createBrowserRouter([
  {
    element: <RootLayout />,
    errorElement: <RouteErrorPage />,
    children: [
      { path: "/", element: <HomeRedirectPage /> },
      { path: "/login", element: <LoginPage /> },
      { path: "/onboarding/create-workspace", element: <CreateWorkspacePage /> },
      { path: "/developer/api", element: <DeveloperApiPage /> },
      { path: `${W}/overview`, element: <OverviewPage /> },
      { path: `${W}/projects`, element: <ProjectsPage /> },
      { path: `${W}/projects/:projectId`, element: <ProjectDetailPage /> },
      { path: `${W}/collections`, element: <CollectionsPage /> },
      { path: `${W}/collections/:collectionId/data`, element: <CollectionDataPage /> },
      { path: `${W}/collections/:collectionId/queries`, element: <CollectionQueriesPage /> },
      { path: `${W}/collections/:collectionId/schema`, element: <CollectionSchemaPage /> },
      { path: `${W}/jobs`, element: <JobsPage /> },
      { path: `${W}/keys`, element: <KeysPage /> },
      { path: `${W}/mcp`, element: <McpPage /> },
      { path: `${W}/webhooks`, element: <WebhooksPage /> },
      { path: `${W}/audit`, element: <AuditPage /> },
      { path: `${W}/analytics`, element: <AnalyticsPage /> },
      { path: `${W}/members`, element: <MembersPage /> },
      { path: `${W}/settings`, element: <SettingsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
