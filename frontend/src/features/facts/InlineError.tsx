import { AlertTriangle } from 'lucide-react'
import { Alert, AlertDescription } from '../../components/ui/alert'

/** Review error line on Facts and in identity review; destructive alerts announce themselves with `role="alert"`. */
export function InlineError({ message }: { message: string }) {
  return <Alert variant="destructive" className="my-[4px]"><AlertTriangle /><AlertDescription>{message}</AlertDescription></Alert>
}
