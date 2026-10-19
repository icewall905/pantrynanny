import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { post } from '../api/client'
import type { Product } from '../api/types'
import { useToast } from '../components/Toast'
import { ProductForm } from '../components/ProductForm'
import { Card, PageHeader } from '../components/ui'

export default function NewProductPage() {
  const { t } = useTranslation()
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => post<Product>('/products', body),
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: ['products'] })
      toast.push(t('common.saved'), 'success')
      nav(`/products/${p.id}`, { replace: true })
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })
  return (
    <>
      <PageHeader title={t('product.new')} />
      <Card>
        <ProductForm creating saving={create.isPending} onSubmit={(b) => create.mutate(b)} onCancel={() => nav(-1)} />
      </Card>
    </>
  )
}
