import MDEditor from "@uiw/react-md-editor"
import { zodResolver } from "@hookform/resolvers/zod"
import { Globe2, Languages, Loader2, Save, Upload } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { Controller, useForm, useWatch } from "react-hook-form"
import { useTranslation } from "react-i18next"
import { Link, useLocation, useNavigate, useParams } from "react-router-dom"
import { toast } from "sonner"
import { z } from "zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { EmptyState } from "@/components/empty-state"
import { Field } from "@/components/field"
import { SimpleSelect } from "@/components/simple-select"
import { useTheme } from "@/components/theme-provider"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { usePost } from "@/hooks/use-blogger-queries"
import { api } from "@/lib/api"
import { firstSiteLanguage, languageOptionsWithValue, siteLanguageLabel } from "@/lib/languages"
import { slugify } from "@/lib/utils"
import type { Category, Post, PostPayload, Site } from "@/types"

const NONE_VALUE = "__none__"

const postSchema = z.object({
  title: z.string().min(1),
  slug: z.string().min(1),
  language: z.string().min(1),
  markdownContent: z.string().min(1),
  categoryId: z.string(),
  excerpt: z.string().optional(),
  coverImageUrl: z.string().optional(),
  metaTitle: z.string().optional(),
  metaDescription: z.string().optional(),
  canonicalUrl: z.string().optional(),
})

type PostFormValues = z.infer<typeof postSchema>

type TranslationSelectionState = {
  key: string
  languages: string[]
  overwriteExisting: boolean
}

export function PostEditorPage({
  token,
  site,
  categories,
}: {
  token: string
  site: Site | null
  categories: Category[]
}) {
  const { t } = useTranslation()
  const { theme } = useTheme()
  const { postId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [translationDialogOpen, setTranslationDialogOpen] = useState(false)
  const [translationSelection, setTranslationSelection] = useState<TranslationSelectionState | null>(null)
  const postQuery = usePost(token, site?.id ?? null, postId ?? null)
  const editing = postQuery.data ?? null
  const defaultLanguage = firstSiteLanguage(site)
  const form = useForm<PostFormValues>({
    resolver: zodResolver(postSchema),
    defaultValues: emptyPostForm(defaultLanguage),
  })
  const coverImageUrl = useWatch({ control: form.control, name: "coverImageUrl" })
  const selectedLanguage = useWatch({ control: form.control, name: "language" })
  const languageOptions = languageOptionsWithValue(site, selectedLanguage)
  const translationLanguageOptions = useMemo(
    () => (site?.languages ?? []).filter((language) => language.key !== editing?.language),
    [editing?.language, site?.languages]
  )
  const defaultTranslationLanguages = useMemo(
    () => translationLanguageOptions.map((language) => language.key),
    [translationLanguageOptions]
  )
  const translationSelectionKey = `${editing?.id ?? ""}:${defaultTranslationLanguages.join(",")}`
  const activeTranslationSelection =
    translationSelection?.key === translationSelectionKey ? translationSelection : null
  const selectedTranslationLanguages = activeTranslationSelection?.languages ?? defaultTranslationLanguages
  const overwriteExistingTranslations = activeTranslationSelection?.overwriteExisting ?? false
  const canGenerateTranslations =
    Boolean(editing) && selectedTranslationLanguages.length > 0 && translationLanguageOptions.length > 0
  const postsHref = getPostsHref(location.state)

  useEffect(() => {
    form.reset(editing ? formFromPost(editing) : emptyPostForm(defaultLanguage))
  }, [defaultLanguage, editing, form])

  const saveMutation = useMutation({
    mutationFn: (values: PostFormValues) => {
      const payload = normalizePostPayload(values)
      if (postId) {
        return api.updatePost(token, site?.id ?? "", postId, payload)
      }
      return api.createPost(token, site?.id ?? "", payload)
    },
    onSuccess: async (saved) => {
      toast.success(t("posts.saved"))
      await queryClient.invalidateQueries({ queryKey: ["posts", token, site?.id ?? null] })
      await queryClient.invalidateQueries({ queryKey: ["post", token, site?.id ?? null, saved.id] })
      if (!postId) {
        navigate(`/posts/${saved.id}/edit`, { replace: true, state: location.state })
      }
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : String(error)),
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => api.uploadImage(token, file, "cover"),
    onSuccess: (response) => {
      form.setValue("coverImageUrl", response.url, { shouldDirty: true })
      toast.success(t("uploads.coverUploaded"))
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : String(error)),
  })

  const generateTranslationsMutation = useMutation({
    mutationFn: () =>
      api.generateTranslations(token, site?.id ?? "", editing?.id ?? "", {
        languages: selectedTranslationLanguages,
        overwrite_existing: overwriteExistingTranslations,
      }),
    onSuccess: async (response) => {
      const created = response.results.filter((item) => item.action === "created").length
      const updated = response.results.filter((item) => item.action === "updated").length
      const skipped = response.results.filter((item) => item.action === "skipped").length
      toast.success(t("posts.translationsGeneratedSummary", { created, updated, skipped }))
      setTranslationDialogOpen(false)
      await queryClient.invalidateQueries({ queryKey: ["posts", token, site?.id ?? null] })
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : String(error)),
  })

  function handleTitleChange(value: string) {
    form.setValue("title", value, { shouldDirty: true })
    if (!form.getValues("slug")) {
      form.setValue("slug", slugify(value), { shouldDirty: true })
    }
  }

  function toggleTranslationLanguage(language: string) {
    setTranslationSelection((current) => {
      const selection =
        current?.key === translationSelectionKey
          ? current
          : {
              key: translationSelectionKey,
              languages: defaultTranslationLanguages,
              overwriteExisting: false,
            }
      const languages = selection.languages.includes(language)
        ? selection.languages.filter((value) => value !== language)
        : [...selection.languages, language]

      return { ...selection, languages }
    })
  }

  function setOverwriteTranslations(value: boolean) {
    setTranslationSelection((current) => {
      const selection =
        current?.key === translationSelectionKey
          ? current
          : {
              key: translationSelectionKey,
              languages: defaultTranslationLanguages,
              overwriteExisting: false,
            }

      return { ...selection, overwriteExisting: value }
    })
  }

  if (!site) {
    return <EmptyState icon={<Globe2 />} title={t("posts.createSiteFirst")} />
  }

  if (postId && postQuery.isLoading) {
    return <Skeleton className="h-[520px]" />
  }

  return (
    <form className="space-y-4" onSubmit={form.handleSubmit((values) => saveMutation.mutate(values))}>
      <Card>
        <CardHeader>
          <div>
            <CardTitle>{postId ? t("posts.edit") : t("posts.new")}</CardTitle>
            <CardDescription>{site.name}</CardDescription>
          </div>
          <CardAction className="flex gap-2">
            <Button type="button" variant="outline" asChild>
              <Link to={postsHref}>{t("common.cancel")}</Link>
            </Button>
            {editing ? (
              <Button
                type="button"
                variant="outline"
                disabled={translationLanguageOptions.length === 0}
                onClick={() => setTranslationDialogOpen(true)}
              >
                <Languages />
                {t("posts.generateTranslations")}
              </Button>
            ) : null}
            <Button type="submit" disabled={saveMutation.isPending}>
              {saveMutation.isPending ? <Loader2 className="animate-spin" /> : <Save />}
              {t("common.save")}
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label={t("posts.title")} required>
              <Controller
                control={form.control}
                name="title"
                render={({ field }) => (
                  <Input value={field.value} onChange={(event) => handleTitleChange(event.target.value)} />
                )}
              />
            </Field>
            <Field label={t("posts.slug")} required>
              <Controller
                control={form.control}
                name="slug"
                render={({ field }) => (
                  <Input
                    value={field.value}
                    onChange={(event) => form.setValue("slug", slugify(event.target.value), { shouldDirty: true })}
                  />
                )}
              />
            </Field>
            <Field label={t("posts.language")}>
              <Controller
                control={form.control}
                name="language"
                render={({ field }) => (
                  <SimpleSelect value={field.value} onValueChange={field.onChange} options={languageOptions} />
                )}
              />
            </Field>
            <Field label={t("posts.category")}>
              <Controller
                control={form.control}
                name="categoryId"
                render={({ field }) => (
                  <SimpleSelect
                    value={field.value}
                    onValueChange={field.onChange}
                    options={[
                      { value: NONE_VALUE, label: t("common.none") },
                      ...categories.map((category) => ({ value: category.id, label: category.name })),
                    ]}
                  />
                )}
              />
            </Field>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("posts.seo")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label={t("posts.metaTitle")}>
              <Input {...form.register("metaTitle")} />
            </Field>
            <Field label={t("posts.canonicalUrl")}>
              <Input {...form.register("canonicalUrl")} />
            </Field>
          </div>
          <Field label={t("posts.metaDescription")}>
            <Textarea className="min-h-20" {...form.register("metaDescription")} />
          </Field>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label={t("posts.coverImage")}>
              <div className="flex items-center gap-2">
                <Input
                  type="file"
                  accept="image/*"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) uploadMutation.mutate(file)
                  }}
                />
                <Button type="button" variant="outline" size="icon" disabled={uploadMutation.isPending}>
                  {uploadMutation.isPending ? <Loader2 className="animate-spin" /> : <Upload />}
                </Button>
              </div>
              {coverImageUrl ? (
                <img
                  className="mt-3 h-28 w-48 rounded-lg border object-cover"
                  src={coverImageUrl}
                  alt=""
                />
              ) : null}
            </Field>
            <Field label={t("posts.excerpt")}>
              <Input {...form.register("excerpt")} />
            </Field>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            {t("posts.markdown")}
            <span className="ml-1 text-destructive">*</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Controller
            control={form.control}
            name="markdownContent"
            render={({ field }) => (
              <div data-color-mode={theme === "dark" ? "dark" : "light"}>
                <MDEditor height={520} value={field.value} onChange={(value) => field.onChange(value ?? "")} />
              </div>
            )}
          />
        </CardContent>
      </Card>

      <Dialog open={translationDialogOpen} onOpenChange={setTranslationDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("posts.generateTranslations")}</DialogTitle>
            <DialogDescription>
              {t("posts.generateTranslationsDescription", {
                language: siteLanguageLabel(site, editing?.language ?? defaultLanguage),
              })}
            </DialogDescription>
          </DialogHeader>
          {translationLanguageOptions.length ? (
            <div className="space-y-4">
              <Field label={t("posts.targetLanguages")} required>
                <div className="flex flex-wrap gap-2">
                  {translationLanguageOptions.map((language) => {
                    const selected = selectedTranslationLanguages.includes(language.key)
                    return (
                      <Button
                        key={language.key}
                        type="button"
                        size="sm"
                        variant={selected ? "default" : "outline"}
                        onClick={() => toggleTranslationLanguage(language.key)}
                      >
                        {language.label} ({language.key})
                      </Button>
                    )
                  })}
                </div>
              </Field>
              <label className="flex items-center gap-2 text-sm text-muted-foreground">
                <input
                  type="checkbox"
                  className="size-4"
                  checked={overwriteExistingTranslations}
                  onChange={(event) => setOverwriteTranslations(event.target.checked)}
                />
                <span>{t("posts.overwriteDraftTranslations")}</span>
              </label>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t("posts.noTranslationTargets")}</p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setTranslationDialogOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              type="button"
              disabled={!canGenerateTranslations || generateTranslationsMutation.isPending}
              onClick={() => generateTranslationsMutation.mutate()}
            >
              {generateTranslationsMutation.isPending ? <Loader2 className="animate-spin" /> : <Languages />}
              {t("posts.generateDrafts")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </form>
  )
}

function formFromPost(post: Post): PostFormValues {
  return {
    title: post.title,
    slug: post.slug,
    language: post.language,
    markdownContent: post.markdown_content,
    categoryId: post.category_id || NONE_VALUE,
    excerpt: post.excerpt || "",
    coverImageUrl: post.cover_image_url || "",
    metaTitle: post.meta_title || "",
    metaDescription: post.meta_description || "",
    canonicalUrl: post.canonical_url || "",
  }
}

function getPostsHref(state: unknown) {
  if (!isPostsListState(state)) {
    return "/posts"
  }

  return `/posts${state.postsListSearch}`
}

function isPostsListState(state: unknown): state is { postsListSearch: string } {
  return (
    typeof state === "object" &&
    state !== null &&
    "postsListSearch" in state &&
    typeof state.postsListSearch === "string" &&
    (state.postsListSearch === "" || state.postsListSearch.startsWith("?"))
  )
}

function emptyPostForm(language: string): PostFormValues {
  return {
    title: "",
    slug: "",
    language,
    markdownContent: "",
    categoryId: NONE_VALUE,
    excerpt: "",
    coverImageUrl: "",
    metaTitle: "",
    metaDescription: "",
    canonicalUrl: "",
  }
}

function normalizePostPayload(values: PostFormValues): PostPayload {
  return {
    title: values.title,
    slug: values.slug,
    language: values.language,
    markdown_content: values.markdownContent,
    excerpt: values.excerpt || null,
    cover_image_url: values.coverImageUrl || null,
    meta_title: values.metaTitle || null,
    meta_description: values.metaDescription || null,
    canonical_url: values.canonicalUrl || null,
    category_id: values.categoryId === NONE_VALUE ? null : values.categoryId,
  }
}
