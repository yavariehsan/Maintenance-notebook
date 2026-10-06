import { DatabasesScreen } from '@/custom/screens/assets/DatabasesScreen'

// Routing boundary stays here; screen composition lives downstream.
// The /assets route serves the دیتابیس section with its two tabs:
// دیتابیس اطلاعات تجهیزات + دیتابیس حالت خرابی تجهیزات.
export default function AssetsPage() {
  return <DatabasesScreen />
}
