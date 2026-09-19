type PanelCloseButtonProps = {
  label: string;
  onClick: () => void;
};

export function PanelCloseButton({ label, onClick }: PanelCloseButtonProps) {
  return (
    <button className="panel-close" type="button" onClick={onClick} aria-label={label}>
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="m6 6 12 12M18 6 6 18" />
      </svg>
    </button>
  );
}
