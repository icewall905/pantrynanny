import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Compass } from 'lucide-react'
import { EmptyState } from '../components/ui'

export default function NotFoundPage() {
  const { t } = useTranslation()
  return (
    <EmptyState
      icon={<Compass className="size-8" />}
      title={t('notFound.title')}
      hint={t('notFound.hint')}
      action={
        <Link to="/" className="inline-flex min-h-11 items-center rounded-xl bg-leaf-600 px-4 font-semibold text-white">
          {t('notFound.home')}
        </Link>
      }
    />
  )
}
