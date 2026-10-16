import type { ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Alert, AlertDescription } from './ui/alert'

/** Inline error line for a failed request; `children` holds an optional recovery action such as Retry. Destructive alerts
 * announce themselves with `role="alert"`. */
export function InlineError({ message, children }: { message: ReactNode; children?: ReactNode }) {
  return <Alert variant="destructive" className="my-[4px]"><AlertTriangle /><AlertDescription>{message}{children}</AlertDescription></Alert>
}
