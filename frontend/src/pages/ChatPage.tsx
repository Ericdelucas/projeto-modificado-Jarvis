import { ChatArea } from '../components/Chat/ChatArea';
import { SystemPanel } from '../components/Chat/SystemPanel';
import { useAppStore } from '../lib/store';

export function ChatPage({ embeddedHud = false }: { embeddedHud?: boolean }) {
  const systemPanelOpen = useAppStore((s) => s.systemPanelOpen);

  return (
    <div className="flex h-full overflow-hidden">
      <div className="flex-1 min-w-0">
        <ChatArea embeddedHud={embeddedHud} />
      </div>
      {systemPanelOpen && <SystemPanel />}
    </div>
  );
}
