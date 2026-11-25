import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom"
import { toast } from "sonner"
import { useQueryClient } from "@tanstack/react-query"

import { AdminSidebar } from "@/components/admin-sidebar"
import { AdminTopbar } from "@/components/admin-topbar"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Skeleton } from "@/components/ui/skeleton"
import { AuthScreen } from "@/features/auth/auth-screen"
import { AccessKeysView } from "@/features/access-keys/access-keys-view"
import { CategoriesView } from "@/features/categories/categories-view"
import { PostEditorPage } from "@/features/posts/post-editor-page"
import { PostsListPage } from "@/features/posts/posts-list-page"
import { ProfileView } from "@/features/profile/profile-view"
import { SitesView } from "@/features/sites/sites-view"
import { UsersView } from "@/features/users/users-view"
import {
  queryKeys,
  useAccessKeys,
  useCategories,
  useMe,
  useSites,
  useUsers,
} from "@/hooks/use-blogger-queries"
import { getAdminPageTitle } from "@/lib/admin-routes"
import { ApiError } from "@/lib/api"
import { useAuth } from "@/context/auth-context"

export function AppShell() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const { token, user, setUser, signOut } = useAuth()
  const [selectedSiteId, setSelectedSiteId] = useState("")
  const [isSwitchingSite, setIsSwitchingSite] = useState(false)

  const meQuery = useMe(token)
  const sitesQuery = useSites(token)
  const accessKeysQuery = useAccessKeys(token)
  const activeUser = user ?? meQuery.data ?? null
  const isSuperAdmin = activeUser?.role === "super_admin"
  const usersQuery = useUsers(token, isSuperAdmin)
  const sites = useMemo(() => sitesQuery.data ?? [], [sitesQuery.data])
  const effectiveSiteId = useMemo(() => {
    if (selectedSiteId && sites.some((site) => site.id === selectedSiteId)) {
      return selectedSiteId
    }
    return sites[0]?.id || ""
  }, [selectedSiteId, sites])
  const selectedSite = useMemo(
    () => sites.find((site) => site.id === effectiveSiteId) ?? null,
    [effectiveSiteId, sites]
  )
  const categoriesQuery = useCategories(token, selectedSite?.id ?? null)

  useEffect(() => {
    if (meQuery.data) {
      setUser(meQuery.data)
    }
  }, [meQuery.data, setUser])

  useEffect(() => {
    const error =
      meQuery.error ||
      sitesQuery.error ||
      accessKeysQuery.error ||
      categoriesQuery.error ||
      usersQuery.error

    if (!error) {
      return
    }

    if (error instanceof ApiError && error.status === 401) {
      signOut()
      return
    }

    toast.error(error instanceof Error ? error.message : String(error))
  }, [
    accessKeysQuery.error,
    categoriesQuery.error,
    meQuery.error,
    signOut,
    sitesQuery.error,
    usersQuery.error,
  ])

  if (!token) {
    return <AuthScreen />
  }

  if (meQuery.isLoading && !activeUser) {
    return <AppSkeleton />
  }

  if (!isSuperAdmin && ["/sites", "/users"].some((path) => location.pathname.startsWith(path))) {
    return <Navigate to="/posts" replace />
  }

  async function refreshAll() {
    await queryClient.invalidateQueries()
  }

  async function refreshSite(siteId: string) {
    if (!token) {
      return
    }

    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.categories(token, siteId) }),
      queryClient.invalidateQueries({ queryKey: ["posts", token, siteId] }),
      queryClient.invalidateQueries({ queryKey: ["post", token, siteId] }),
    ])
  }

  async function handleSelectSite(siteId: string) {
    if (!siteId || siteId === effectiveSiteId) {
      return
    }

    setSelectedSiteId(siteId)
    if (/^\/posts\/[^/]+\/edit$/.test(location.pathname)) {
      navigate("/posts")
    }

    setIsSwitchingSite(true)
    try {
      await refreshSite(siteId)
    } finally {
      setIsSwitchingSite(false)
    }
  }

  return (
    <SidebarProvider>
      <AdminSidebar isSuperAdmin={isSuperAdmin} pathname={location.pathname} />
      <SidebarInset>
        <AdminTopbar
          title={getAdminPageTitle(location.pathname, t)}
          selectedSite={selectedSite}
          sites={sites}
          isRefreshing={isSwitchingSite || sitesQuery.isFetching || categoriesQuery.isFetching}
          onSelectSite={(siteId) => void handleSelectSite(siteId)}
          onRefresh={() => void refreshAll()}
          user={activeUser}
          isSuperAdmin={isSuperAdmin}
          onProfile={() => navigate("/profile")}
          onSignOut={signOut}
        />

        <div className="flex flex-1 flex-col gap-4 p-4 md:p-6">
          <Routes>
            <Route path="/" element={<Navigate to="/posts" replace />} />
            <Route
              path="/posts"
              element={
                <PostsListPage
                  key={selectedSite?.id ?? "none"}
                  token={token}
                  site={selectedSite}
                  categories={categoriesQuery.data ?? []}
                />
              }
            />
            <Route
              path="/posts/new"
              element={
                <PostEditorPage token={token} site={selectedSite} categories={categoriesQuery.data ?? []} />
              }
            />
            <Route
              path="/posts/:postId/edit"
              element={
                <PostEditorPage token={token} site={selectedSite} categories={categoriesQuery.data ?? []} />
              }
            />
            <Route
              path="/categories"
              element={
                <CategoriesView token={token} site={selectedSite} categories={categoriesQuery.data ?? []} />
              }
            />
            <Route
              path="/keys"
              element={<AccessKeysView token={token} accessKeys={accessKeysQuery.data ?? []} sites={sites} />}
            />
            <Route
              path="/profile"
              element={
                activeUser ? <ProfileView token={token} user={activeUser} onUserChange={setUser} /> : null
              }
            />
            <Route
              path="/sites"
              element={
                isSuperAdmin ? (
                  <SitesView
                    token={token}
                    sites={sites}
                    selectedSiteId={selectedSite?.id ?? ""}
                    onSelectSite={(siteId) => void handleSelectSite(siteId)}
                  />
                ) : (
                  <Navigate to="/posts" replace />
                )
              }
            />
            <Route
              path="/users"
              element={isSuperAdmin ? <UsersView token={token} users={usersQuery.data ?? []} /> : <Navigate to="/posts" replace />}
            />
            <Route path="*" element={<Navigate to="/posts" replace />} />
          </Routes>
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}

function AppSkeleton() {
  return (
    <div className="flex min-h-svh flex-col gap-4 p-6">
      <Skeleton className="h-10 w-56" />
      <div className="grid gap-4 md:grid-cols-[16rem_1fr]">
        <Skeleton className="h-[calc(100svh-5rem)]" />
        <Skeleton className="h-[calc(100svh-5rem)]" />
      </div>
    </div>
  )
}
