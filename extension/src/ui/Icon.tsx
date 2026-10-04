/** Small, consistent line icons. No font or network dependency. */
export function Icon({ name }: { name: 'history' | 'settings' | 'move' | 'close' | 'reset' }) {
  const paths = {
    history: 'M5 4h11a2 2 0 0 1 2 2v14H7a3 3 0 0 1-3-3V5a1 1 0 0 1 1-1Zm2 0v12m0 0H4m6-8h5m-5 4h5',
    settings: 'M4 7h16M4 17h16M9 4v6m6 4v6',
    move: 'M12 3v18M3 12h18m-12-6 3-3 3 3m-6 12 3 3 3-3M6 9l-3 3 3 3m12-6 3 3-3 3',
    close: 'm6 6 12 12M18 6 6 18',
    reset: 'M4 10a8 8 0 1 1 2 8M4 4v6h6',
  };
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={paths[name]} />
    </svg>
  );
}
