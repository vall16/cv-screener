import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService, Job } from './api.service';
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

  private pollId: ReturnType<typeof setInterval> | null = null;

  constructor(private api: ApiService) {}

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
    }
  }

  async refreshAll(): Promise<void> {
    try {
      const r = await firstValueFrom(this.api.listCvs());
      this.cvs = r.cvs;
    } catch {
      this.uploadError = 'Backend non raggiungibile. Avvia il backend (python backend/main.py).';
    }
    await this.loadJobs();
    await this.loadReports();
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

  async start(): Promise<void> {
    if (!this.profile.trim()) {
      this.uploadError = 'Inserisci il profilo target.';
      return;
    }
    this.uploadError = '';
    this.job = null;
    try {
      const r = await firstValueFrom(this.api.startJob(this.profile.trim()));
      this.job = r.job;
      this.step = 'run';
      this.startPolling();
      await this.loadJobs();
    } catch (e: unknown) {
      const err = e as { error?: { detail?: string } };
      this.uploadError = err?.error?.detail ?? 'Impossibile avviare lo screening.';
    }
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
    try {
      const r = await firstValueFrom(this.api.listReports());
      this.reports = r.reports;
      if (r.reports.length && !r.reports.includes(this.activeReport)) {
        this.activeReport = r.reports.includes('classifica.md')
          ? 'classifica.md'
          : r.reports[0];
        await this.openReport(this.activeReport);
      }
    } catch {
      this.reports = [];
    }
  }

  async openReport(name: string): Promise<void> {
    this.activeReport = name;
    this.loadingReport = true;
    try {
      const r = await firstValueFrom(this.api.getReport(name));
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
      await this.loadReports();
      this.step = 'results';
    }
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