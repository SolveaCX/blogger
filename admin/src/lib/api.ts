import type {
  AccessKey,
  AccessKeyCreated,
  Category,
  Post,
  PostListParams,
  PostListResponse,
  PostPayload,
  Site,
  SiteLanguage,
  TokenResponse,
  TranslationGeneratePayload,
  TranslationGenerateResponse,
  User,
} from '../types'

export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

type RequestOptions = RequestInit & {
  token?: string | null
}

type SitePayload = {
  name: string
  slug: string
  base_url?: string | null
  description?: string | null
  languages?: SiteLanguage[]
}

export class ApiError extends Error {
  status: number
  payload: unknown

  constructor(status: number, message: string, payload: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (options.token) {
    headers.set('Authorization', `Bearer ${options.token}`)
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
  })

  if (response.status === 204) {
    return undefined as T
  }

  const contentType = response.headers.get('Content-Type') || ''
  const payload = contentType.includes('application/json') ? await response.json() : await response.text()

  if (!response.ok) {
    const detail =
      typeof payload === 'object' && payload && 'detail' in payload ? String(payload.detail) : response.statusText
    throw new ApiError(response.status, detail, payload)
  }

  return payload as T
}

function queryString(params: Record<string, string | number | undefined | null>) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value))
    }
  })
  const value = search.toString()
  return value ? `?${value}` : ''
}

export const api = {
  login: (email: string, password: string) =>
    request<TokenResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  register: (email: string, password: string, nickname?: string) =>
    request<TokenResponse>('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, nickname }),
    }),
  me: (token: string) => request<User>('/api/users/me', { token }),
  updateMe: (token: string, payload: Pick<User, 'nickname' | 'avatar_url'>) =>
    request<User>('/api/users/me', {
      method: 'PATCH',
      token,
      body: JSON.stringify(payload),
    }),
  listUsers: (token: string) => request<User[]>('/api/users', { token }),
  updateUser: (token: string, id: string, payload: Partial<Pick<User, 'nickname' | 'avatar_url' | 'role' | 'is_active'>>) =>
    request<User>(`/api/users/${id}`, {
      method: 'PATCH',
      token,
      body: JSON.stringify(payload),
    }),
  uploadImage: (token: string, file: File, kind: string) => {
    const form = new FormData()
    form.set('kind', kind)
    form.set('file', file)
    return request<{ url: string }>('/api/uploads', {
      method: 'POST',
      token,
      body: form,
    })
  },
  listAccessKeys: (token: string) => request<AccessKey[]>('/api/access-keys', { token }),
  createAccessKey: (token: string, name: string, siteId?: string) =>
    request<AccessKeyCreated>('/api/access-keys', {
      method: 'POST',
      token,
      body: JSON.stringify({ name, site_id: siteId }),
    }),
  revokeAccessKey: (token: string, id: string) =>
    request<AccessKey>(`/api/access-keys/${id}`, {
      method: 'DELETE',
      token,
    }),
  listSites: (token: string) => request<Site[]>('/api/sites', { token }),
  createSite: (token: string, payload: SitePayload) =>
    request<Site>('/api/sites', {
      method: 'POST',
      token,
      body: JSON.stringify(payload),
    }),
  updateSite: (token: string, id: string, payload: Partial<SitePayload>) =>
    request<Site>(`/api/sites/${id}`, {
      method: 'PATCH',
      token,
      body: JSON.stringify(payload),
    }),
  deleteSite: (token: string, id: string) =>
    request<void>(`/api/sites/${id}`, {
      method: 'DELETE',
      token,
    }),
  listCategories: (token: string, siteId: string) =>
    request<Category[]>(`/api/sites/${siteId}/categories`, { token }),
  createCategory: (token: string, siteId: string, payload: Pick<Category, 'name' | 'slug' | 'description'>) =>
    request<Category>(`/api/sites/${siteId}/categories`, {
      method: 'POST',
      token,
      body: JSON.stringify(payload),
    }),
  updateCategory: (
    token: string,
    siteId: string,
    categoryId: string,
    payload: Partial<Pick<Category, 'name' | 'slug' | 'description'>>,
  ) =>
    request<Category>(`/api/sites/${siteId}/categories/${categoryId}`, {
      method: 'PATCH',
      token,
      body: JSON.stringify(payload),
    }),
  deleteCategory: (token: string, siteId: string, categoryId: string) =>
    request<void>(`/api/sites/${siteId}/categories/${categoryId}`, {
      method: 'DELETE',
      token,
    }),
  listPosts: (token: string, siteId: string, params: PostListParams = {}) =>
    request<PostListResponse>(`/api/sites/${siteId}/posts${queryString(params)}`, { token }),
  createPost: (token: string, siteId: string, payload: PostPayload) =>
    request<Post>(`/api/sites/${siteId}/posts`, {
      method: 'POST',
      token,
      body: JSON.stringify(payload),
    }),
  getPost: (token: string, siteId: string, postId: string) =>
    request<Post>(`/api/sites/${siteId}/posts/${postId}`, { token }),
  updatePost: (token: string, siteId: string, postId: string, payload: Partial<PostPayload>) =>
    request<Post>(`/api/sites/${siteId}/posts/${postId}`, {
      method: 'PATCH',
      token,
      body: JSON.stringify(payload),
    }),
  generateTranslations: (token: string, siteId: string, postId: string, payload: TranslationGeneratePayload) =>
    request<TranslationGenerateResponse>(`/api/sites/${siteId}/posts/${postId}/translations/generate`, {
      method: 'POST',
      token,
      body: JSON.stringify(payload),
    }),
  publishPost: (token: string, siteId: string, postId: string) =>
    request<Post>(`/api/sites/${siteId}/posts/${postId}/publish`, {
      method: 'POST',
      token,
    }),
  unpublishPost: (token: string, siteId: string, postId: string) =>
    request<Post>(`/api/sites/${siteId}/posts/${postId}/unpublish`, {
      method: 'POST',
      token,
    }),
  deletePost: (token: string, siteId: string, postId: string) =>
    request<void>(`/api/sites/${siteId}/posts/${postId}`, {
      method: 'DELETE',
      token,
    }),
}
