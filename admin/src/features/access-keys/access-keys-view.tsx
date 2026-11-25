import { zodResolver } from "@hookform/resolvers/zod"
import { Loader2, Plus, Trash2 } from "lucide-react"
import { useState } from "react"
import { useController, useForm } from "react-hook-form"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { z } from "zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { Field } from "@/components/field"
import { SimpleSelect } from "@/components/simple-select"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { queryKeys } from "@/hooks/use-blogger-queries"
import { api, API_URL } from "@/lib/api"
import { formatDate } from "@/lib/utils"
import type { AccessKey, AccessKeyCreated, Site } from "@/types"

const accountScope = "account"

const keySchema = z.object({
  name: z.string().min(1),
  siteScope: z.string().min(1),
})

type KeyFormValues = z.infer<typeof keySchema>

export function AccessKeysView({
  token,
  accessKeys,
  sites,
}: {
  token: string
  accessKeys: AccessKey[]
  sites: Site[]
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [created, setCreated] = useState<AccessKeyCreated | null>(null)
  const form = useForm<KeyFormValues>({
    resolver: zodResolver(keySchema),
    defaultValues: {
      name: "",
      siteScope: accountScope,
    },
  })
  const { field: siteScopeField } = useController({ control: form.control, name: "siteScope" })

  const createMutation = useMutation({
    mutationFn: ({ name, siteScope }: KeyFormValues) =>
      api.createAccessKey(token, name, siteScope === accountScope ? undefined : siteScope),
    onSuccess: async (key) => {
      setCreated(key)
      form.reset()
      toast.success(t("keys.created"))
      await queryClient.invalidateQueries({
        queryKey: queryKeys.accessKeys(token),
      })
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : String(error))
    },
  })

  const revokeMutation = useMutation({
    mutationFn: (key: AccessKey) => api.revokeAccessKey(token, key.id),
    onSuccess: async () => {
      toast.success(t("keys.revoked"))
      await queryClient.invalidateQueries({
        queryKey: queryKeys.accessKeys(token),
      })
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : String(error))
    },
  })

  function revokeKey(key: AccessKey) {
    if (window.confirm(t("keys.confirmRevoke", { name: key.name }))) {
      revokeMutation.mutate(key)
    }
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[420px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle>{t("keys.createTitle")}</CardTitle>
          <CardDescription>{t("keys.sharedKey")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-4"
            onSubmit={form.handleSubmit((values) =>
              createMutation.mutate(values)
            )}
          >
            <Field label={t("keys.name")}>
              <Input {...form.register("name")} />
            </Field>
            <Field label={t("keys.scope")}>
              <SimpleSelect
                aria-label={t("keys.scope")}
                value={siteScopeField.value}
                onValueChange={siteScopeField.onChange}
                options={[
                  { value: accountScope, label: t("keys.accountScope") },
                  ...sites.map((site) => ({ value: site.id, label: site.name })),
                ]}
              />
              <p className="text-xs text-muted-foreground">{t("keys.siteScopeHelp")}</p>
            </Field>
            <Button type="submit" disabled={createMutation.isPending}>
              {createMutation.isPending ? (
                <Loader2 className="animate-spin" />
              ) : (
                <Plus />
              )}
              {t("common.create")}
            </Button>
          </form>
          {created ? (
            <div className="mt-4 rounded-lg border bg-muted/50 p-3">
              <div className="mb-2 text-sm font-medium">
                {t("keys.newKey")}
              </div>
              <div className="mb-2 text-xs text-muted-foreground">
                {t("keys.copyOnce")}
              </div>
              <Input
                className="font-mono"
                value={created.access_key}
                readOnly
                onFocus={(event) => event.currentTarget.select()}
              />
              <div className="mt-3 text-xs text-muted-foreground">
                {t("keys.mcpUrl")}{" "}
                <code className="break-all">{API_URL.replace(/\/$/, "")}/api/mcp</code>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("keys.list")}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2">
          {accessKeys.map((key) => (
            <div
              key={key.id}
              className="flex items-center justify-between gap-4 rounded-lg border p-3"
            >
              <div className="min-w-0">
                <div className="font-medium">{key.name}</div>
                <CardDescription className="font-mono">
                  {key.key_prefix}...
                </CardDescription>
                <div className="text-xs text-muted-foreground">
                  {key.site_id
                    ? t("keys.siteScope", {
                        site: sites.find((site) => site.id === key.site_id)?.name ?? key.site_id,
                      })
                    : t("keys.accountScope")}
                </div>
                <div className="text-xs text-muted-foreground">
                  {t("common.lastUsed", { date: formatDate(key.last_used_at) })}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant={key.revoked_at ? "destructive" : "outline"}>
                  {key.revoked_at ? t("common.revoked") : t("common.active")}
                </Badge>
                {!key.revoked_at ? (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => revokeKey(key)}
                    aria-label={t("keys.revoke")}
                  >
                    <Trash2 />
                  </Button>
                ) : null}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
