import { Component, Injector, OnDestroy, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { afterNextRender, ViewChild } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService, Candidate, CvDetail, Job, Session, ProfileTemplate, TrackingEntry, ShortlistEntry } from './api.service';
import { renderMarkdown } from './markdown';

type Step = 'upload' | 'run' | 'results' | 'tracking';

export type ToastType = 'ok' | 'err' | 'info';

interface Toast {
  id: number;
  text: string;
  type: ToastType;
  out?: boolean;
}

interface ConfirmState {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  danger: boolean;
}

interface PromptState {
  open: boolean;
  title: string;
  value: string;
}

@Component({
  selector: 'app-root',
  imports: [CommonModule, FormsModule],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnInit, OnDestroy {
  @ViewChild('indeedTerminal') indeedTerminal!: { nativeElement: HTMLElement };
  private injector = inject(Injector);
  step: Step = 'upload';
  theme: 'light' | 'dark' = 'light';

  toasts: Toast[] = [];
  private toastSeq = 0;
  confirmState: ConfirmState = { open: false, title: '', message: '', confirmLabel: 'Conferma', danger: true };
  private confirmResolve: ((v: boolean) => void) | null = null;
  promptState: PromptState = { open: false, title: '', value: '' };
  private promptResolve: ((v: string | null) => void) | null = null;

  cvs: string[] = [];
  cvDetails: Record<string, CvDetail> = {};
  cvFilter = '';
  selectedFiles: File[] = [];
  uploading = false;

  profile = '';
  templates: ProfileTemplate[] = [];
  job: Job | null = null;
  jobs: Job[] = [];
  history: Job[] = [];

  reports: string[] = [];
  activeReport = '';
  activeHtml = '';
  loadingReport = false;

  // Tabella candidati (risultati interattivi)
  candidates: Candidate[] = [];
  candFilterGiudizio = 'all'; // 'all' | 'Sì passa' | 'Da valutare' | 'No'
  candFilterStatus = 'all'; // 'all' | 'interview' | 'rejected' | 'offer' | 'none'
  candMinScore = 0;
  candSearch = '';
  candSortField: 'score' | 'name' = 'score';
  candSortDir: 'asc' | 'desc' = 'desc';
  shortlist: Record<string, ShortlistEntry> = {};

  // Tracking (vista globale)
  tracking: TrackingEntry[] = [];
  trackView: 'board' | 'table' = 'board';
  trackFilterStatus = 'all';
  trackFilterSession = 'all';
  trackSearch = '';
  trackSortField: 'score' | 'name' | 'updated_at' = 'updated_at';
  trackSortDir: 'asc' | 'desc' = 'desc';

  // Pipeline: fasi in ordine visivo (lo stato vuoto '' = "Nuovo").
  trackStages: { key: string; label: string }[] = [
    { key: '', label: 'Nuovo' },
    { key: 'screened', label: 'Screanato' },
    { key: 'interview', label: 'Da intervistare' },
    { key: 'interviewed', label: 'Intervistato' },
    { key: 'offer', label: 'Offerta' },
    { key: 'hired', label: 'Assunto' },
    { key: 'rejected', label: 'Scartato' },
  ];

  csvUrl(): string {
    return this.api.reportsSummaryCsvUrl(this.activeSessionId || undefined);
  }

  jsonUrl(): string {
    return this.api.reportsSummaryJsonUrl(this.activeSessionId || undefined);
  }

  // Sessioni (posizioni)
  sessions: Session[] = [];
  activeSessionId = ''; // '' = report legacy (senza posizione)
  newSessionName = '';
  newSessionCvs: string[] = [];
  creatingSession = false;

  private pollId: ReturnType<typeof setInterval> | null = null;

  constructor(protected api: ApiService) {}

  async ngOnInit(): Promise<void> {
    this.applySavedTheme();
    await this.refreshAll();
    await this.loadTemplates();
    if (!this.job || this.job.status !== 'running') {
      const running = this.history.find((j) => j.status === 'running');
      if (running) {
        this.job = running;
        this.step = 'run';
        this.startPolling();
      }
    }
  }

  ngOnDestroy(): void {
    this.stopPolling();
    this.stopIndeedPolling();
  }

  md(src: string): string {
    return renderMarkdown(src);
  }

  go(step: Step): void {
    this.step = step;
    if (step === 'results') {
      void this.loadReports();
    }
    if (step === 'tracking') {
      void this.loadTracking();
    }
    if (step === 'upload' || step === 'run') {
      void this.loadJobs();
      void this.loadSessions();
    }
  }

  stepIndex(): number {
    return this.step === 'upload' ? 0 : this.step === 'run' ? 1 : this.step === 'results' ? 2 : 3;
  }

  applySavedTheme(): void {
    let saved: string | null = null;
    try {
      saved = localStorage.getItem('theme');
    } catch {
      saved = null;
    }
    const t =
      saved === 'light' || saved === 'dark'
        ? saved
        : window.matchMedia('(prefers-color-scheme: dark)').matches
          ? 'dark'
          : 'light';
    this.applyTheme(t);
  }

  applyTheme(t: 'light' | 'dark'): void {
    this.theme = t;
    document.documentElement.dataset['theme'] = t;
    try {
      localStorage.setItem('theme', t);
    } catch {
      // storage non disponibile: il tema vale solo per questa sessione
    }
  }

  toggleTheme(): void {
    this.applyTheme(this.theme === 'light' ? 'dark' : 'light');
  }

  // ── Toast ─────────────────────────────────────────
  showToast(text: string, type: ToastType = 'info', ms = 4000): void {
    const id = ++this.toastSeq;
    this.toasts = [...this.toasts, { id, text, type }];
    if (ms > 0) {
      setTimeout(() => this.dismissToast(id), ms);
    }
  }

  dismissToast(id: number): void {
    this.toasts = this.toasts.map((t) => (t.id === id ? { ...t, out: true } : t));
    setTimeout(() => {
      this.toasts = this.toasts.filter((t) => t.id !== id);
    }, 250);
  }

  toastIcon(type: ToastType): string {
    return type === 'ok' ? '✓' : type === 'err' ? '✕' : 'ℹ';
  }

  // ── Dialoghi (confirm / prompt) ───────────────────
  askConfirm(opts: {
    title: string;
    message: string;
    confirmLabel?: string;
    danger?: boolean;
  }): Promise<boolean> {
    this.confirmState = {
      open: true,
      title: opts.title,
      message: opts.message,
      confirmLabel: opts.confirmLabel ?? 'Conferma',
      danger: opts.danger ?? true,
    };
    return new Promise<boolean>((resolve) => {
      this.confirmResolve = resolve;
    });
  }

  resolveConfirm(value: boolean): void {
    const resolve = this.confirmResolve;
    this.confirmResolve = null;
    this.confirmState = { ...this.confirmState, open: false };
    resolve?.(value);
  }

  askPrompt(title: string, value = ''): Promise<string | null> {
    this.promptState = { open: true, title, value };
    return new Promise<string | null>((resolve) => {
      this.promptResolve = resolve;
    });
  }

  resolvePrompt(value: string | null): void {
    const resolve = this.promptResolve;
    this.promptResolve = null;
    this.promptState = { ...this.promptState, open: false };
    resolve?.(value);
  }

  goResults(): void {
    if (this.job?.session_id) this.activeSessionId = this.job.session_id;
    this.go('results');
  }

  async refreshAll(): Promise<void> {
    await this.loadCvs();
    await this.loadJobs();
    await this.loadSessions();
    await this.loadReports();
    await this.loadIndeedArchive();
  }

  async loadCvs(): Promise<void> {
    try {
      const r = await firstValueFrom(this.api.listCvs());
      this.cvs = r.cvs;
      this.cvDetails = {};
      for (const d of r.details ?? []) {
        this.cvDetails[d.name] = d;
      }
    } catch {
      this.showToast('Il backend non è raggiungibile. Avvia il backend (python backend/main.py).', 'err', 8000);
    }
  }

  async loadIndeedArchive(): Promise<void> {
    try {
      const r = await firstValueFrom(this.api.indeedArchive());
      this.indeedArchive = r.count;
      this.indeedArchiveAvailable = r.available;
    } catch {
      this.indeedArchiveAvailable = false;
    }
  }

  onFilesSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.selectedFiles = Array.from(input.files ?? []);
  }

  dragOver = false;

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragOver = true;
  }

  onDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.dragOver = false;
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragOver = false;
    const files = Array.from(event.dataTransfer?.files ?? []);
    if (files.length) {
      this.selectedFiles = files;
    }
  }

  async upload(): Promise<void> {
    if (!this.selectedFiles.length) {
      return;
    }
    this.uploading = true;
    try {
      const r = await firstValueFrom(this.api.upload(this.selectedFiles));
      const errors = r.errors ?? [];
      errors.forEach((e) => this.showToast(e, 'err', 6000));
      const saved = r.saved?.length ?? 0;
      if (saved) {
        this.showToast(`${saved} file caricato${saved === 1 ? '' : 'i'}.`, 'ok');
      }
      await this.loadCvs();
      (document.getElementById('files') as HTMLInputElement | null)?.value && ((document.getElementById('files') as HTMLInputElement).value = '');
      this.selectedFiles = [];
    } catch {
      this.showToast('Upload fallito. Il backend è raggiungibile? (http://127.0.0.1:8000)', 'err', 6000);
    } finally {
      this.uploading = false;
    }
  }

  async deleteCv(name: string): Promise<void> {
    try {
      await firstValueFrom(this.api.deleteCv(name));
      this.cvs = this.cvs.filter((c) => c !== name);
      delete this.cvDetails[name];
      this.showToast(`${name} eliminato.`, 'ok');
    } catch {
      this.showToast(`Impossibile eliminare ${name}.`, 'err');
    }
  }

  cvExt(name: string): string {
    const i = name.lastIndexOf('.');
    return i >= 0 ? name.slice(i + 1).toUpperCase() : 'FILE';
  }

  cvClass(name: string): string {
    const e = this.cvExt(name);
    if (e === 'PDF') return 'pdf';
    if (e === 'DOCX') return 'docx';
    return 'txt';
  }

  openCv(name: string): void {
    window.open(this.api.cvFileUrl(name), '_blank', 'noopener');
  }

  formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    const kb = bytes / 1024;
    if (kb < 1024) return `${kb.toFixed(0)} kB`;
    return `${(kb / 1024).toFixed(1)} MB`;
  }

  formatDate(iso: string): string {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString('it-IT', { day: '2-digit', month: 'short', year: 'numeric' });
  }

  cvMetaLabel(name: string): string {
    const d = this.cvDetails[name];
    if (!d) return '';
    return `${this.formatSize(d.size)} · ${this.formatDate(d.mtime)}`;
  }

  get filteredCvs(): string[] {
    const q = this.cvFilter.trim().toLowerCase();
    if (!q) return this.cvs;
    return this.cvs.filter((c) => c.toLowerCase().includes(q));
  }

  async deleteAllCvs(): Promise<void> {
    const total = this.cvs.length;
    const ok = await this.askConfirm({
      title: 'Eliminare tutti i CV?',
      message: `Verranno rimossi ${total} file da CVs/. L'operazione non è reversibile.`,
      confirmLabel: 'Elimina tutti',
      danger: true,
    });
    if (!ok) return;
    try {
      const r = await firstValueFrom(this.api.deleteAllCvs());
      this.cvs = [];
      this.cvDetails = {};
      this.showToast(`${r.count} CV eliminati.`, 'ok');
    } catch {
      this.showToast('Impossibile eliminare tutti i CV.', 'err');
    }
  }

  // ── Sessioni (posizioni) ──────────────────────────
  async loadSessions(): Promise<void> {
    try {
      const r = await firstValueFrom(this.api.listSessions());
      this.sessions = r.sessions;
    } catch {
      this.sessions = [];
    }
  }

  async createNewSession(): Promise<void> {
    if (!this.newSessionName.trim()) {
      this.showToast('Inserisci il nome della posizione.', 'err');
      return;
    }
    if (!this.profile.trim()) {
      this.showToast('Inserisci il profilo target.', 'err');
      return;
    }
    if (!this.newSessionCvs.length) {
      this.showToast('Seleziona almeno un CV per la posizione.', 'err');
      return;
    }
    this.creatingSession = true;
    try {
      const s = await firstValueFrom(
        this.api.createSession(this.newSessionName.trim(), this.profile.trim(), this.newSessionCvs),
      );
      await this.loadSessions();
      this.newSessionName = '';
      this.profile = '';
      this.newSessionCvs = [];
      this.activeSessionId = s.id;
      this.showToast(`Posizione "${s.name}" creata.`, 'ok');
    } catch (e: unknown) {
      const err = e as { error?: { detail?: string } };
      this.showToast(err?.error?.detail ?? 'Impossibile creare la posizione.', 'err');
    } finally {
      this.creatingSession = false;
    }
  }

  async deleteSession(s: Session): Promise<void> {
    const ok = await this.askConfirm({
      title: 'Eliminare la posizione?',
      message: `"${s.name}" e i suoi report verranno rimossi definitivamente.`,
      confirmLabel: 'Elimina',
      danger: true,
    });
    if (!ok) return;
    try {
      await firstValueFrom(this.api.deleteSession(s.id));
      if (this.activeSessionId === s.id) this.activeSessionId = '';
      await this.loadSessions();
      this.showToast(`Posizione "${s.name}" eliminata.`, 'ok');
    } catch {
      this.showToast('Impossibile eliminare la posizione.', 'err');
    }
  }

  toggleCvSelection(name: string): void {
    const i = this.newSessionCvs.indexOf(name);
    if (i >= 0) this.newSessionCvs.splice(i, 1);
    else this.newSessionCvs.push(name);
  }

  selectAllCvs(): void {
    this.newSessionCvs = [...this.cvs];
  }

  deselectAllCvs(): void {
    this.newSessionCvs = [];
  }

  async startSessionScreening(s: Session): Promise<void> {
    if (!s.cvs.length) {
      this.showToast('La posizione non ha CV selezionati.', 'err');
      return;
    }
    this.job = null;
    try {
      const r = await firstValueFrom(this.api.startJob(s.profile, s.id, s.cvs));
      this.job = r.job;
      this.step = 'run';
      this.startPolling();
      this.showToast('Screening avviato.', 'ok');
      await this.loadJobs();
    } catch (e: unknown) {
      const err = e as { error?: { detail?: string } };
      this.showToast(err?.error?.detail ?? 'Impossibile avviare lo screening.', 'err');
    }
  }

  async switchSession(sessionId: string): Promise<void> {
    this.activeSessionId = sessionId;
    this.activeReport = '';
    this.activeHtml = '';
    this.candFilterGiudizio = 'all';
    this.candMinScore = 0;
    this.candSearch = '';
    await this.loadReports();
  }

  startPolling(): void {
    this.stopPolling();
    this.pollId = setInterval(() => {
      if (!this.job || this.job.status !== 'running') {
        return;
      }
      void this.poll();
    }, 2500);
  }

  stopPolling(): void {
    if (this.pollId) {
      clearInterval(this.pollId);
      this.pollId = null;
    }
  }

  private pollErrors = 0;

  async poll(): Promise<void> {
    if (!this.job) {
      return;
    }
    try {
      const r = await firstValueFrom(this.api.getJob(this.job.id));
      this.pollErrors = 0;
      this.job = r.job;
      if (this.job.status !== 'running') {
        this.stopPolling();
        this.notifyJobComplete(this.job);
        if (this.job.session_id) this.activeSessionId = this.job.session_id;
        await this.loadReports();
        await this.loadJobs();
      }
    } catch {
      this.pollErrors++;
      if (this.pollErrors >= 5) {
        this.stopPolling();
      }
    }
  }

  async loadJobs(): Promise<void> {
    try {
      const r = await firstValueFrom(this.api.listJobs());
      this.history = r.jobs;
    } catch {
      this.history = [];
    }
  }

  async loadReports(): Promise<void> {
    const session = this.activeSessionId || undefined;
    try {
      const r = await firstValueFrom(this.api.listReports(session));
      this.reports = r.reports;
      if (r.reports.length && !r.reports.includes(this.activeReport)) {
        this.activeReport = r.reports.includes('classifica.md')
          ? 'classifica.md'
          : r.reports[0];
        await this.openReport(this.activeReport);
      } else if (!r.reports.length) {
        this.activeReport = '';
        this.activeHtml = '';
      }
    } catch {
      this.reports = [];
    }
    await this.loadCandidates();
  }

  async loadCandidates(): Promise<void> {
    const session = this.activeSessionId || undefined;
    try {
      const r = await firstValueFrom(this.api.listCandidates(session));
      this.candidates = r.candidates;
    } catch {
      this.candidates = [];
    }
    await this.loadShortlist();
  }

  async loadShortlist(): Promise<void> {
    const session = this.activeSessionId || undefined;
    try {
      const r = await firstValueFrom(this.api.getShortlist(session));
      this.shortlist = r.shortlist;
    } catch {
      this.shortlist = {};
    }
  }

  async setCandidateStatus(file: string, status: string): Promise<void> {
    if (!this.activeSessionId) return;
    const note = this.shortlist[file]?.note ?? '';
    // optimistic update
    if (status === '' && !note) {
      delete this.shortlist[file];
    } else {
      this.shortlist[file] = { status, note, updated_at: new Date().toISOString() };
    }
    try {
      const r = await firstValueFrom(this.api.setShortlistStatus(this.activeSessionId, file, status, note));
      this.shortlist = r.shortlist;
    } catch {
      await this.loadShortlist();
    }
  }

  shortlistStatusLabel(s: string): string {
    switch (s) {
      case 'screened': return 'Screanato';
      case 'interview': return 'Da intervistare';
      case 'interviewed': return 'Intervistato';
      case 'offer': return 'Offerta';
      case 'hired': return 'Assunto';
      case 'rejected': return 'Scartato';
      default: return '';
    }
  }

  // ── Tracking (vista globale) ──────────────────────
  async loadTracking(): Promise<void> {
    try {
      const r = await firstValueFrom(this.api.getTracking());
      this.tracking = r.candidates;
    } catch {
      this.tracking = [];
    }
  }

  async updateTrackingStatus(entry: TrackingEntry, status: string): Promise<void> {
    const note = entry.note;
    entry.status = status;
    entry.updated_at = new Date().toISOString();
    try {
      await firstValueFrom(this.api.setShortlistStatus(entry.session_id, entry.file, status, note));
    } catch {
      await this.loadTracking();
    }
  }

  async updateTrackingNote(entry: TrackingEntry, note: string): Promise<void> {
    entry.note = note;
    entry.updated_at = new Date().toISOString();
    try {
      await firstValueFrom(this.api.setShortlistStatus(entry.session_id, entry.file, entry.status, note));
    } catch {
      await this.loadTracking();
    }
  }

  visibleTracking(): TrackingEntry[] {
    let list = this.tracking;
    if (this.trackFilterStatus !== 'all') {
      list = list.filter((t) => t.status === this.trackFilterStatus);
    }
    if (this.trackFilterSession !== 'all') {
      list = list.filter((t) => t.session_id === this.trackFilterSession);
    }
    const q = this.trackSearch.trim().toLowerCase();
    if (q) {
      list = list.filter((t) => t.name.toLowerCase().includes(q));
    }
    const dir = this.trackSortDir === 'asc' ? 1 : -1;
    return [...list].sort((a, b) => {
      if (this.trackSortField === 'score') {
        return ((a.score ?? -1) - (b.score ?? -1)) * dir;
      }
      if (this.trackSortField === 'updated_at') {
        return (a.updated_at.localeCompare(b.updated_at)) * dir;
      }
      return a.name.localeCompare(b.name, 'it') * dir;
    });
  }

  trackCounts(): Record<string, number> {
    const counts: Record<string, number> = { all: this.tracking.length };
    for (const t of this.tracking) {
      counts[t.status] = (counts[t.status] ?? 0) + 1;
    }
    return counts;
  }

  trackPipelineCount(): number {
    const pipeline = ['screened', 'interview', 'interviewed'];
    return this.tracking.filter((t) => pipeline.includes(t.status)).length;
  }

  // ── Pipeline (board a colonne) ─────────────────────
  // Colonne del board: applica i filtri posizione + ricerca (non lo stato,
  // che è già la colonna). Ogni fase raggruppa i candidati con quel status.
  trackBoardColumns(): { key: string; label: string; items: TrackingEntry[] }[] {
    const q = this.trackSearch.trim().toLowerCase();
    const filtered = this.tracking.filter((t) => {
      if (this.trackFilterSession !== 'all' && t.session_id !== this.trackFilterSession) return false;
      if (q && !t.name.toLowerCase().includes(q)) return false;
      return true;
    });
    return this.trackStages.map((s) => ({
      key: s.key,
      label: s.label,
      items: filtered.filter((t) => (t.status || '') === s.key),
    }));
  }

  trackStageIndex(status: string): number {
    return this.trackStages.findIndex((s) => s.key === (status || ''));
  }

  // Sposta un candidato alla fase precedente/successiva (frecce ← →).
  moveTrackStage(entry: TrackingEntry, dir: -1 | 1): void {
    const next = this.trackStageIndex(entry.status) + dir;
    if (next < 0 || next >= this.trackStages.length) return;
    void this.updateTrackingStatus(entry, this.trackStages[next].key);
  }

  trackSessions(): { id: string; name: string }[] {
    const seen = new Map<string, string>();
    for (const t of this.tracking) {
      if (t.session_id && !seen.has(t.session_id)) {
        seen.set(t.session_id, t.session_name);
      }
    }
    return [...seen.entries()].map(([id, name]) => ({ id, name }));
  }

  trackSortArrow(field: string): string {
    if (this.trackSortField !== field) return '';
    return this.trackSortDir === 'asc' ? ' ↑' : ' ↓';
  }

  trackToggleSort(field: 'score' | 'name' | 'updated_at'): void {
    if (this.trackSortField === field) {
      this.trackSortDir = this.trackSortDir === 'asc' ? 'desc' : 'asc';
    } else {
      this.trackSortField = field;
      this.trackSortDir = field === 'score' ? 'desc' : 'asc';
    }
  }

  trackFormatDate(iso: string): string {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString('it-IT', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
  }

  // Candidati dopo filtri + ordinamento (ricomputato a ogni change detection).
  visibleCandidates(): Candidate[] {
    let list = this.candidates;
    if (this.candFilterGiudizio !== 'all') {
      list = list.filter((c) => c.giudizio === this.candFilterGiudizio);
    }
    if (this.candFilterStatus !== 'all') {
      list = list.filter((c) => {
        const s = this.shortlist[c.file]?.status || '';
        if (this.candFilterStatus === 'none') return !s;
        return s === this.candFilterStatus;
      });
    }
    if (this.candMinScore > 0) {
      list = list.filter((c) => c.score !== null && c.score >= this.candMinScore);
    }
    const q = this.candSearch.trim().toLowerCase();
    if (q) {
      list = list.filter((c) => c.name.toLowerCase().includes(q));
    }
    const dir = this.candSortDir === 'asc' ? 1 : -1;
    return [...list].sort((a, b) => {
      if (this.candSortField === 'score') {
        return ((a.score ?? -1) - (b.score ?? -1)) * dir;
      }
      return a.name.localeCompare(b.name, 'it') * dir;
    });
  }

  candCounts(): { pass: number; eval: number; no: number; total: number } {
    let pass = 0;
    let ev = 0;
    let no = 0;
    for (const c of this.candidates) {
      if (c.giudizio === 'Sì passa') pass++;
      else if (c.giudizio === 'Da valutare') ev++;
      else if (c.giudizio === 'No') no++;
    }
    return { pass, eval: ev, no, total: this.candidates.length };
  }

  toggleSort(field: 'score' | 'name'): void {
    if (this.candSortField === field) {
      this.candSortDir = this.candSortDir === 'asc' ? 'desc' : 'asc';
    } else {
      this.candSortField = field;
      this.candSortDir = field === 'score' ? 'desc' : 'asc';
    }
  }

  sortArrow(field: 'score' | 'name'): string {
    if (this.candSortField !== field) return '';
    return this.candSortDir === 'asc' ? ' ↑' : ' ↓';
  }

  openCandidate(c: Candidate): void {
    void this.openReport(c.file);
  }

  giudizioClass(g: string | null): string {
    if (g === 'Sì passa') return 'pass';
    if (g === 'Da valutare') return 'eval';
    if (g === 'No') return 'no';
    return '';
  }

  async openReport(name: string): Promise<void> {
    this.activeReport = name;
    this.loadingReport = true;
    try {
      const r = await firstValueFrom(this.api.getReport(name, this.activeSessionId || undefined));
      this.activeHtml = renderMarkdown(r.content);
    } catch {
      this.activeHtml = '<p>Errore nel caricamento del report.</p>';
    } finally {
      this.loadingReport = false;
    }
  }

  async cancelJob(): Promise<void> {
    if (!this.job || this.job.status !== 'running') return;
    const ok = await this.askConfirm({
      title: 'Fermare lo screening?',
      message: 'Il processo opencode verrà terminato. I report già scritti restano.',
      confirmLabel: 'Ferma',
      danger: true,
    });
    if (!ok) return;
    try {
      await firstValueFrom(this.api.cancelJob(this.job.id));
      this.stopPolling();
      this.job = { ...this.job, status: 'cancelled', error: 'Job annullato dall\'utente' };
      this.showToast('Screening fermato.', 'ok');
    } catch {
      this.showToast('Impossibile fermare lo screening.', 'err');
    }
  }

  async openJob(j: Job): Promise<void> {
    this.job = j;
    this.step = 'run';
    if (j.status === 'running') {
      this.startPolling();
    } else if (j.status === 'done') {
      if (j.session_id) this.activeSessionId = j.session_id;
      await this.loadReports();
      this.step = 'results';
    }
  }

  async deleteJob(j: Job): Promise<void> {
    const ok = await this.askConfirm({
      title: 'Eliminare lo screening?',
      message: `"${j.profile}" e il suo esito verranno rimossi.`,
      confirmLabel: 'Elimina',
      danger: true,
    });
    if (!ok) return;
    try {
      await firstValueFrom(this.api.deleteJob(j.id));
      await this.loadJobs();
      this.showToast('Screening eliminato.', 'ok');
    } catch {
      this.showToast('Impossibile eliminare lo screening.', 'err');
    }
  }

  indeedSyncing = false;
  indeedArchive = 0;
  indeedArchiveAvailable = false;
  indeedClearing = false;

  // ── Indeed modal (terminale in-app) ──
  indeedModalOpen = false;
  indeedLines: string[] = [];
  indeedOffset = 0;
  indeedRunning = false;
  indeedInputText = '';
  private indeedPollId: ReturnType<typeof setInterval> | null = null;

  indeedStarting = false;

  async launchIndeed(): Promise<void> {
    if (this.indeedStarting) return;
    this.indeedStarting = true;
    this.openIndeedModal();
    try {
      await firstValueFrom(this.api.indeedLaunch());
      this.indeedLines = ['Downloader avviato. In attesa del menu…'];
    } catch (e: unknown) {
      const err = e as { error?: { detail?: string } };
      this.indeedLines = ['ERRORE: ' + (err?.error?.detail ?? 'Impossibile avviare il downloader.')];
      this.indeedRunning = false;
    } finally {
      this.indeedStarting = false;
    }
  }

  openIndeedModal(): void {
    this.indeedModalOpen = true;
    this.indeedLines = [];
    this.indeedOffset = 0;
    this.indeedRunning = true;
    this.indeedInputText = '';
    this.startIndeedPolling();
  }

  closeIndeedModal(): void {
    this.stopIndeedPolling();
    this.indeedModalOpen = false;
    this.indeedRunning = false;
    // Ferma anche il processo se ancora attivo
    void firstValueFrom(this.api.indeedStop()).catch(() => {});
  }

  private startIndeedPolling(): void {
    this.stopIndeedPolling();
    this.indeedPollId = setInterval(() => {
      void this.indeedPoll();
    }, 1500);
  }

  private stopIndeedPolling(): void {
    if (this.indeedPollId) {
      clearInterval(this.indeedPollId);
      this.indeedPollId = null;
    }
  }

  private async indeedPoll(): Promise<void> {
    try {
      const r = await firstValueFrom(this.api.indeedStream(this.indeedOffset));
      if (r.lines.length) {
        this.indeedLines.push(...r.lines);
        this.indeedOffset = r.total;
        this.scrollIndeedTerminal();
      }
      this.indeedRunning = r.running;
      if (!r.running) {
        this.stopIndeedPolling();
      }
    } catch {
      // backend non raggiungibile: ignora
    }
  }

  private scrollIndeedTerminal(): void {
    afterNextRender(
      () => {
        if (this.indeedTerminal) {
          this.indeedTerminal.nativeElement.scrollTop = this.indeedTerminal.nativeElement.scrollHeight;
        }
      },
      { injector: this.injector }
    );
  }

  async indeedSendInput(): Promise<void> {
    const text = this.indeedInputText;
    this.indeedInputText = '';
    if (!text) return;
    this.indeedLines.push(`❯ ${text}`);
    this.scrollIndeedTerminal();
    try {
      await firstValueFrom(this.api.indeedInput(text));
    } catch {
      // processo non più attivo
    }
  }

  async indeedStopProcess(): Promise<void> {
    try {
      await firstValueFrom(this.api.indeedStop());
    } catch {
      // ignore
    }
    this.indeedRunning = false;
    this.stopIndeedPolling();
  }

  async syncIndeed(): Promise<void> {
    this.indeedSyncing = true;
    try {
      const r = await firstValueFrom(this.api.indeedSync());
      await this.loadCvs();
      if (r.count > 0 && r.duplicates > 0) {
        this.showToast(`${r.count} CV importati, ${r.duplicates} duplicati saltati.`, 'ok');
      } else if (r.count > 0) {
        this.showToast(`${r.count} CV importati da Indeed.`, 'ok');
      } else if (r.duplicates > 0) {
        this.showToast(`Nessun nuovo CV: ${r.duplicates} duplicati saltati.`, 'info');
      } else {
        this.showToast('Nessun nuovo CV da Indeed.', 'info');
      }
      await this.loadIndeedArchive();
    } catch (e: unknown) {
      const err = e as { error?: { detail?: string } };
      this.showToast(err?.error?.detail ?? 'Sincronizzazione fallita.', 'err', 6000);
    } finally {
      this.indeedSyncing = false;
    }
  }

  async clearIndeed(): Promise<void> {
    if (!this.indeedArchiveAvailable) {
      this.showToast('Nessun archivio Indeed trovato.', 'info');
      return;
    }
    if (this.indeedArchive === 0) {
      this.showToast('Archivio Indeed già vuoto.', 'info');
      return;
    }
    const n = this.indeedArchive;
    const ok = await this.askConfirm({
      title: 'Svuotare l\'archivio Indeed?',
      message:
        `Eliminare definitivamente i ${n} PDF dall'archivio Indeed? ` +
        'Non passano dal cestino, quindi non sono recuperabili. ' +
        'I CV già importati in CVs/ restano: per rimuoverli usa "Elimina tutti".',
      confirmLabel: 'Svuota archivio',
      danger: true,
    });
    if (!ok) {
      return;
    }
    this.indeedClearing = true;
    try {
      const r = await firstValueFrom(this.api.indeedClear());
      this.indeedArchive = r.count;
      this.showToast(
        r.deleted > 0 ? `${r.deleted} PDF eliminati dall'archivio Indeed.` : 'Nessun file da eliminare.',
        r.deleted > 0 ? 'ok' : 'info'
      );
    } catch (e: unknown) {
      const err = e as { error?: { detail?: string } };
      this.showToast(err?.error?.detail ?? 'Eliminazione archivio fallita.', 'err', 6000);
    } finally {
      this.indeedClearing = false;
    }
  }

  pdfUrl(name: string): string {
    return this.api.reportPdfUrl(name, this.activeSessionId || undefined);
  }

  printReport(): void {
    window.print();
  }

  isClassifica(name: string): boolean {
    return name.toLowerCase().includes('classifica');
  }

  statusLabel(job: Job): string {
    switch (job.status) {
      case 'running':
        return 'In corso';
      case 'done':
        return 'Completato';
      case 'cancelled':
        return 'Fermato';
      case 'interrupted':
        return 'Interrotto';
      default:
        return 'Errore';
    }
  }

  // --- Template profilo ---

  async loadTemplates(): Promise<void> {
    try {
      const r = await firstValueFrom(this.api.listProfiles());
      this.templates = r.profiles;
    } catch {
      this.templates = [];
    }
  }

  applyTemplate(event: Event): void {
    const sel = event.target as HTMLSelectElement;
    const tpl = this.templates.find(t => t.id === sel.value);
    if (tpl) {
      this.profile = tpl.profile;
    }
    sel.value = '';
  }

  async saveTemplate(): Promise<void> {
    if (!this.profile.trim()) return;
    const name = await this.askPrompt('Nome del template', this.newSessionName || 'Profilo');
    if (!name?.trim()) return;
    try {
      await firstValueFrom(this.api.saveProfile(name.trim(), this.profile.trim()));
      await this.loadTemplates();
      this.showToast(`Template "${name.trim()}" salvato.`, 'ok');
    } catch {
      this.showToast('Impossibile salvare il template.', 'err');
    }
  }

  // --- Notifica browser ---

  private notifyJobComplete(job: Job): void {
    if (!('Notification' in window)) return;
    if (Notification.permission === 'default') {
      Notification.requestPermission();
      return;
    }
    if (Notification.permission === 'granted') {
      const label = job.status === 'done' ? '✓ Completato' : '✗ Errore';
      new Notification('CV Screener', { body: `Screening ${label}` });
    }
  }
}