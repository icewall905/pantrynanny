import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChefHat } from 'lucide-react'
import { useAiStatus } from '../api/queries'
import { EmptyState, PageHeader, Spinner, Tabs } from '../components/ui'
import ChatPanel from '../components/assistant/ChatPanel'
import RecipesPanel from '../components/assistant/RecipesPanel'

export default function AssistantPage() {
  const { t, i18n } = useTranslation()
  const ai = useAiStatus()
  const [tab, setTab] = useState<'chat' | 'recipes'>('chat')
  const locale = i18n.language?.startsWith('en') ? 'en' : 'da'
  if (ai.isLoading) return <Spinner />
  if (!ai.data?.enabled || !ai.data.reachable)
    return (
      <>
        <PageHeader title={t('nav.assistant')} />
        <EmptyState icon={<ChefHat className="size-8" />} title={t('assistant.unavailable')} hint={t('assistant.unavailableHint')} />
      </>
    )
  return (
    <>
      <PageHeader title={t('nav.assistant')} subtitle={ai.data.model ?? undefined} />
      <Tabs
        tabs={[
          { id: 'chat', label: t('assistant.tabChat') },
          { id: 'recipes', label: t('assistant.tabRecipes') },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === 'chat' ? <ChatPanel locale={locale} /> : <RecipesPanel locale={locale} />}
    </>
  )
}
