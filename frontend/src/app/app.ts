import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService, Candidate, Job, Session } from './api.service';
import { renderMarkdown } from './markdown';

type Step = 'upload' | 'run' | 'results';

@Component({
  selector: 'app-root',
  imports: [CommonModule, FormsModule],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnInit, OnDestroy {
  step: Step = 'upload';

  cvs: string[] = [];
  selectedFiles: File[] = [];
  uploadErrors: string[] = [];
  uploadError = '';
  uploading = false;

  profile = '';
  job: Job | null = null;
  jobs: Job[] = [];
  history: Job[] = [];

  reports: string[] = [];
  activeReport = '';
  activeHtml = '';
  loadingReport = false;

  // Tabella candidati (risultati interattivi)
  candidates: Candidate[] = [];
  candFilterGiudizio = 'all'; // 'all' | 'Si passa' | 'Da valutare' | 'No'
  candMinScore = 0;
  candSearch = '';
  candSortField: 'score' | 'name' = 'score';
  candSortDir: 'asc' | 'desc' = 'desc';

  // Sessioni (posizioni)
  sessions: Session[] = [];
  activeSessionId = ''; // '' = report legacy (senza posizione)
  newSessionName = '';
  newSessionCvs: string[] = [];
  creatingSession = false;

  private pollId: ReturnType<typeof setInterval> | null = null;

  constructor(protected api: ApiService) {}

  async ngOnInit(): Promise<void> {
    await this.refreshAll();
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
  }

  md(src: string): string {
    return renderMarkdown(src);
  }

  go(step: Step): void {
    this.step = step;
    if (step === 'results') {
      void this.loadReports();
    }
    if (step === 'upload' || step === 'run') {
      void this.loadJobs();
      void this.loadSessions();
    }
  }

  goResults(): void {
    if (this.job?.session_id) this.activeSessionId = this.job.session_id;
    this.go('results');
  }

  async refreshAll(): Promise<void> {
    try {
      const r = await firstValueFrom(this.api.listCvs());
      this.cvs = r.cvs;
    } catch {
      this.uploadError = 'Backend non raggiungibile. Avvia il backend (python backend/main.py).';
    }
    await this.loadJobs();
    await this.loadSessions();
    await this.loadReports();
    await this.loadIndeedArchive();
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

  async upload(): Promise<void> {
    if (!this.selectedFiles.length) {
      return;
    }
    this.uploading = true;
    this.uploadErrors = [];
    this.uploadError = '';
    try {
      const r = await firstValueFrom(this.api.upload(this.selectedFiles));
      this.uploadErrors = r.errors ?? [];
      this.cvs = r.cvs;
      (document.getElementById('files') as HTMLInputElement | null)?.value && ((document.getElementById('files') as HTMLInputElement).value = '');
      this.selectedFiles = [];
    } catch {
      this.uploadError = 'Upload fallito. Il backend e raggiungibile? (http://127.0.0.1:8000)';
    } finally {
      this.uploading = false;
    }
  }

  async deleteCv(name: string): Promise<void> {
    try {
      await firstValueFrom(this.api.deleteCv(name));
      this.cvs = this.cvs.filter((c) => c !== name);
    } catch {
      this.uploadErrors = [`Impossibile eliminare ${name}`];
    }
  }

  async deleteAllCvs(): Promise<void> {
    if (!confirm('Eliminare tutti i CV?')) return;
    try {
      await firstValueFrom(this.api.deleteAllCvs());
      this.cvs = [];
    } catch {
      this.uploadErrors = ['Impossibile eliminare tutti i CV'];
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
      this.uploadError = 'Inserisci il nome della posizione.';
      return;
    }
    if (!this.profile.trim()) {
      this.uploadError = 'Inserisci il profilo target.';
      return;
    }
    if (!this.newSessionCvs.length) {
      this.uploadError = 'Seleziona almeno un CV per la posizione.';
      return;
    }
    this.uploadError = '';
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
    } catch (e: unknown) {
      const err = e as { error?: { detail?: string } };
      this.uploadError = err?.error?.detail ?? 'Impossibile creare la posizione.';
    } finally {
      this.creatingSession = false;
    }
  }

  async deleteSession(s: Session): Promise<void> {
    if (!confirm(`Eliminare la posizione "${s.name}" e i suoi report?`)) return;
    try {
      await firstValueFrom(this.api.deleteSession(s.id));
      if (this.activeSessionId === s.id) this.activeSessionId = '';
      await this.loadSessions();
    } catch {
      this.uploadError = 'Impossibile eliminare la posizione.';
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
      this.uploadError = 'La posizione non ha CV selezionati.';
      return;
    }
    this.uploadError = '';
    this.job = null;
    try {
      const r = await firstValueFrom(this.api.startJob(s.profile, s.id, s.cvs));
      this.job = r.job;
      this.step = 'run';
      this.startPolling();
      await this.loadJobs();
    } catch (e: unknown) {
      const err = e as { error?: { detail?: string } };
      this.uploadError = err?.error?.detail ?? 'Impossibile avviare lo screening.';
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

  async poll(): Promise<void> {
    if (!this.job) {
      return;
    }
    try {
      const r = await firstValueFrom(this.api.getJob(this.job.id));
      this.job = r.job;
      if (this.job.status !== 'running') {
        this.stopPolling();
        if (this.job.session_id) this.activeSessionId = this.job.session_id;
        await this.loadReports();
        await this.loadJobs();
      }
    } catch {
      this.stopPolling();
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
  }

  // Candidati dopo filtri + ordinamento (ricomputato a ogni change detection).
  visibleCandidates(): Candidate[] {
    let list = this.candidates;
    if (this.candFilterGiudizio !== 'all') {
      list = list.filter((c) => c.giudizio === this.candFilterGiudizio);
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
      if (c.giudizio === 'Si passa') pass++;
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
    if (g === 'Si passa') return 'pass';
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

  indeedMsg = '';
  indeedSyncing = false;
  indeedArchive = 0;
  indeedArchiveAvailable = false;
  indeedClearing = false;

  async launchIndeed(): Promise<void> {
    this.indeedMsg = '';
    try {
      const r = await firstValueFrom(this.api.indeedLaunch());
      this.indeedMsg = r.message;
    } catch (e: unknown) {
      const err = e as { error?: { detail?: string } };
      this.indeedMsg = err?.error?.detail ?? 'Impossibile avviare il downloader Indeed.';
    }
  }

  async syncIndeed(): Promise<void> {
    this.indeedSyncing = true;
    this.indeedMsg = '';
    try {
      const r = await firstValueFrom(this.api.indeedSync());
      this.cvs = r.cvs;
      this.indeedMsg = r.count > 0 ? `${r.count} CV importato/i da Indeed.` : 'Nessun nuovo CV da Indeed.';
      await this.loadIndeedArchive();
    } catch (e: unknown) {
      const err = e as { error?: { detail?: string } };
      this.indeedMsg = err?.error?.detail ?? 'Sync fallita.';
    } finally {
      this.indeedSyncing = false;
    }
  }

  async clearIndeed(): Promise<void> {
    if (!this.indeedArchiveAvailable) {
      this.indeedMsg = 'Nessun archivio Indeed trovato.';
      return;
    }
    if (this.indeedArchive === 0) {
      this.indeedMsg = 'Archivio Indeed già vuoto.';
      return;
    }
    const n = this.indeedArchive;
    const ok = confirm(
      `Eliminare definitivamente i ${n} PDF dall'archivio Indeed? ` +
        'Non passano dal cestino, quindi non sono recuperabili.\n\n' +
        'I CV già importati in CVs/ restano: per rimuoverli usa "Elimina tutti".'
    );
    if (!ok) {
      return;
    }
    this.indeedClearing = true;
    this.indeedMsg = '';
    try {
      const r = await firstValueFrom(this.api.indeedClear());
      this.indeedArchive = r.count;
      this.indeedMsg =
        r.deleted > 0
          ? `${r.deleted} PDF eliminati dall'archivio Indeed.`
          : 'Nessun file da eliminare.';
    } catch (e: unknown) {
      const err = e as { error?: { detail?: string } };
      this.indeedMsg = err?.error?.detail ?? 'Eliminazione archivio fallita.';
    } finally {
      this.indeedClearing = false;
    }
  }

  pdfUrl(name: string): string {
    return this.api.reportPdfUrl(name, this.activeSessionId || undefined);
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
      default:
        return 'Errore';
    }
  }
}