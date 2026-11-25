export type User = {
  id: string
  email: string
  nickname: string | null
  avatar_url: string | null
  role: UserRole
  is_active: boolean
  created_at: string
  updated_at: string
}

export type UserRole = 'super_admin' | 'operator'

export type TokenResponse = {
  access_token: string
  token_type: string
  user: User
}

export type AccessKey = {
  id: string
  name: string
  site_id?: string | null
  key_prefix: string
  last_used_at: string | null
  revoked_at: string | null
  created_at: string
}

export type AccessKeyCreated = AccessKey & {
  access_key: string
}

export type Site = {
  id: string
  name: string
  slug: string
  base_url: string | null
  icon_url: string | null
  languages: SiteLanguage[]
  description: string | null
  created_at: string
  updated_at: string
}

export type SiteLanguage = {
  key: string
  label: string
}

export type Category = {
  id: string
  site_id: string
  name: string
  slug: string
  description: string | null
  created_at: string
  updated_at: string
}

export type PostStatus = 'draft' | 'published'

export type Author = {
  id: string
  email: string
  nickname: string | null
  avatar_url: string | null
}

export type Post = {
  id: string
  site_id: string
  author_id: string
  title: string
  slug: string
  language: string
  status: PostStatus
  markdown_content: string
  html_content: string
  excerpt: string | null
  cover_image_url: string | null
  meta_title: string | null
  meta_description: string | null
  canonical_url: string | null
  author_display_name: string | null
  category_id: string | null
  published_at: string | null
  created_at: string
  updated_at: string
  author: Author
  category: Category | null
}

export type PostPayload = {
  title: string
  slug: string
  language: string
  markdown_content: string
  excerpt?: string | null
  cover_image_url?: string | null
  meta_title?: string | null
  meta_description?: string | null
  canonical_url?: string | null
  category_id?: string | null
}

export type PostListResponse = {
  items: Post[]
  total: number
  limit: number
  offset: number
}

export type PostListParams = {
  language?: string
  category_id?: string
  status?: PostStatus | ''
  q?: string
  limit?: number
  offset?: number
}

export type TranslationGeneratePayload = {
  languages: string[]
  overwrite_existing?: boolean
}

export type TranslationGenerateResult = {
  language: string
  action: "created" | "updated" | "skipped"
  reason: string | null
  post_id: string | null
}

export type TranslationGenerateResponse = {
  source_post_id: string
  source_language: string
  results: TranslationGenerateResult[]
}
