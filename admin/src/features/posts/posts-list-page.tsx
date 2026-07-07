import { Edit, Globe2, Plus, Search, Trash2 } from "lucide-react"
import { useCallback, useEffect, useMemo } from "react"
import { Link, useLocation, useSearchParams } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { EmptyState } from "@/components/empty-state"
import { SimpleSelect } from "@/components/simple-select"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { usePosts } from "@/hooks/use-blogger-queries"
import { api } from "@/lib/api"
import { siteLanguageLabel, siteLanguageOptions } from "@/lib/languages"
import { formatDate } from "@/lib/utils"
import type { Category, Post, PostStatus, Site } from "@/types"

const PAGE_SIZE = 10
const ALL_VALUE = "__all__"

type PostsListSearchUpdates = {
  q?: string
  language?: string
  categoryId?: string
  status?: PostStatus | ""
  page?: number
}

export function PostsListPage({
  token,
  site,
  categories,
}: {
  token: string
  site: Site | null
  categories: Category[]
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const query = searchParams.get("q") ?? ""
  const language = searchParams.get("language") ?? ""
  const categoryId = searchParams.get("category_id") ?? ""
  const status = parsePostStatus(searchParams.get("status"))
  const page = parsePageParam(searchParams.get("page"))
  const postsListState = useMemo(() => ({ postsListSearch: location.search }), [location.search])
  const languageOptions = useMemo(() => siteLanguageOptions(site), [site])
  const effectiveLanguage = languageOptions.some((option) => option.value === language) ? language : ""
  const updateListSearch = useCallback(
    (updates: PostsListSearchUpdates, options?: { replace?: boolean }) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current)
          setSearchValue(next, "q", updates.q)
          setSearchValue(next, "language", updates.language)
          setSearchValue(next, "category_id", updates.categoryId)
          setSearchValue(next, "status", updates.status)

          if (updates.page !== undefined) {
            if (updates.page > 0) {
              next.set("page", String(updates.page + 1))
            } else {
              next.delete("page")
            }
          }

          return next
        },
        options
      )
    },
    [setSearchParams]
  )

  const params = useMemo(
    () => ({
      q: query || undefined,
      language: effectiveLanguage,
      category_id: categoryId,
      status,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [categoryId, effectiveLanguage, page, query, status]
  )
  const postsQuery = usePosts(token, site?.id ?? null, params)
  const pageData = postsQuery.data
  const total = pageData?.total ?? 0
  const posts = pageData?.items ?? []
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const from = total === 0 ? 0 : page * PAGE_SIZE + 1
  const to = Math.min(total, (page + 1) * PAGE_SIZE)
  const canGoPrevious = page > 0
  const canGoNext = (page + 1) * PAGE_SIZE < total

  useEffect(() => {
    if (postsQuery.isFetching || total === 0 || page < pageCount) {
      return
    }

    updateListSearch({ page: pageCount - 1 }, { replace: true })
  }, [page, pageCount, postsQuery.isFetching, total, updateListSearch])

  const statusMutation = useMutation({
    mutationFn: ({ post, action }: { post: Post; action: "publish" | "unpublish" }) =>
      action === "publish"
        ? api.publishPost(token, site?.id ?? "", post.id)
        : api.unpublishPost(token, site?.id ?? "", post.id),
    onSuccess: async (_saved, variables) => {
      toast.success(variables.action === "publish" ? t("posts.publishedMessage") : t("posts.draftMessage"))
      await queryClient.invalidateQueries({ queryKey: ["posts", token, site?.id ?? null] })
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : String(error)),
  })

  const deleteMutation = useMutation({
    mutationFn: (post: Post) => api.deletePost(token, site?.id ?? "", post.id),
    onSuccess: async () => {
      toast.success(t("posts.deleted"))
      await queryClient.invalidateQueries({ queryKey: ["posts", token, site?.id ?? null] })
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : String(error)),
  })

  function deletePost(post: Post) {
    if (window.confirm(t("posts.confirmDelete", { title: post.title }))) {
      deleteMutation.mutate(post)
    }
  }

  if (!site) {
    return <EmptyState icon={<Globe2 />} title={t("posts.createSiteFirst")} />
  }

  return (
    <Card>
      <CardHeader className="gap-3 md:flex-row md:items-center md:justify-between">
        <CardTitle>{t("nav.posts")}</CardTitle>
        <Button asChild>
          <Link to="/posts/new" state={postsListState}>
            <Plus />
            {t("posts.new")}
          </Link>
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2 lg:grid-cols-[minmax(220px,1fr)_180px_180px_180px]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-8"
              placeholder={t("posts.search")}
              value={query}
              onChange={(event) => updateListSearch({ q: event.target.value, page: 0 }, { replace: true })}
            />
          </div>
          <SimpleSelect
            value={effectiveLanguage || ALL_VALUE}
            onValueChange={(value) =>
              updateListSearch({ language: value === ALL_VALUE ? "" : value, page: 0 }, { replace: true })
            }
            options={[{ value: ALL_VALUE, label: t("common.allLanguages") }, ...languageOptions]}
          />
          <SimpleSelect
            value={categoryId || ALL_VALUE}
            onValueChange={(value) =>
              updateListSearch({ categoryId: value === ALL_VALUE ? "" : value, page: 0 }, { replace: true })
            }
            options={[{ value: ALL_VALUE, label: t("common.allCategories") }, ...categories.map((category) => ({ value: category.id, label: category.name }))]}
          />
          <SimpleSelect
            value={status || ALL_VALUE}
            onValueChange={(value) =>
              updateListSearch({ status: value === ALL_VALUE ? "" : (value as PostStatus), page: 0 }, { replace: true })
            }
            options={[
              { value: ALL_VALUE, label: t("common.allStatuses") },
              { value: "draft", label: t("common.draft") },
              { value: "published", label: t("common.published") },
            ]}
          />
        </div>

        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("posts.title")}</TableHead>
                <TableHead className="w-24">{t("posts.coverImage")}</TableHead>
                <TableHead>{t("posts.language")}</TableHead>
                <TableHead>{t("posts.category")}</TableHead>
                <TableHead>{t("posts.status")}</TableHead>
                <TableHead>{t("posts.updatedAt")}</TableHead>
                <TableHead className="w-52 text-right">{t("common.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {posts.map((post) => (
                <TableRow key={post.id}>
                  <TableCell>
                    <div className="font-medium">{post.title}</div>
                    <div className="text-xs text-muted-foreground">{t("posts.path", { slug: post.slug })}</div>
                  </TableCell>
                  <TableCell>
                    {post.cover_image_url ? (
                      <img
                        src={post.cover_image_url}
                        alt=""
                        className="h-11 w-16 rounded-md border object-cover"
                        loading="lazy"
                      />
                    ) : (
                      <span className="text-sm text-muted-foreground">{t("common.none")}</span>
                    )}
                  </TableCell>
                  <TableCell>{siteLanguageLabel(site, post.language)}</TableCell>
                  <TableCell>{post.category?.name ?? t("common.none")}</TableCell>
                  <TableCell>
                    <Badge variant={post.status === "published" ? "default" : "outline"}>
                      {post.status === "published" ? t("common.published") : t("common.draft")}
                    </Badge>
                  </TableCell>
                  <TableCell>{formatDate(post.updated_at)}</TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button variant="outline" size="sm" asChild>
                        <Link to={`/posts/${post.id}/edit`} state={postsListState}>
                          <Edit />
                          {t("common.edit")}
                        </Link>
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          statusMutation.mutate({
                            post,
                            action: post.status === "published" ? "unpublish" : "publish",
                          })
                        }
                      >
                        {post.status === "published" ? t("posts.unpublish") : t("posts.publish")}
                      </Button>
                      <Button variant="ghost" size="icon-sm" onClick={() => deletePost(post)} aria-label={t("common.delete")}>
                        <Trash2 />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-sm text-muted-foreground">
            {t("posts.pagination", { from, to, total })}
          </div>
          <Pagination className="mx-0 w-auto justify-end">
            <PaginationContent>
              <PaginationItem>
                <PaginationPrevious
                  href="#"
                  text={t("common.previous")}
                  aria-disabled={!canGoPrevious}
                  className={!canGoPrevious ? "pointer-events-none opacity-50" : undefined}
                  onClick={(event) => {
                    event.preventDefault()
                    if (canGoPrevious) {
                      updateListSearch({ page: Math.max(0, page - 1) })
                    }
                  }}
                />
              </PaginationItem>
              <PaginationItem>
                <PaginationLink href="#" isActive onClick={(event) => event.preventDefault()}>
                  {page + 1}/{pageCount}
                </PaginationLink>
              </PaginationItem>
              <PaginationItem>
                <PaginationNext
                  href="#"
                  text={t("common.next")}
                  aria-disabled={!canGoNext}
                  className={!canGoNext ? "pointer-events-none opacity-50" : undefined}
                  onClick={(event) => {
                    event.preventDefault()
                    if (canGoNext) {
                      updateListSearch({ page: page + 1 })
                    }
                  }}
                />
              </PaginationItem>
            </PaginationContent>
          </Pagination>
        </div>
      </CardContent>
    </Card>
  )
}

function parsePageParam(value: string | null) {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed - 1 : 0
}

function parsePostStatus(value: string | null): PostStatus | "" {
  return value === "draft" || value === "published" ? value : ""
}

function setSearchValue(searchParams: URLSearchParams, key: string, value: string | undefined) {
  if (value === undefined) {
    return
  }

  if (value) {
    searchParams.set(key, value)
  } else {
    searchParams.delete(key)
  }
}
