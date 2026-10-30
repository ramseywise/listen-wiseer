import { Compass } from 'lucide-react'
import { Link } from 'react-router'
import { EmptyState } from '@/components/states/States'
import { Button } from '@/components/ui/button'

export function NotFoundView() {
  return (
    <EmptyState
      icon={<Compass />}
      title="Nothing here"
      action={
        <Button asChild variant="outline" size="sm">
          <Link to="/">Back home</Link>
        </Button>
      }
    >
      That page doesn&apos;t exist.
    </EmptyState>
  )
}
