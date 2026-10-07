import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface CvList {
  cvs: string[];
}

export interface UploadResult {
  saved: string[];
  errors: string[];
  cvs: string[];
}

export type JobStatus = 'running' | 'done' | 'error';

export interface Job {
  id: string;
  status: JobStatus;
  profile: string;
  cv_dir: string;
  session_id: string | null;
  cvs: string[];
  output: string[];
  error: string | null;
  reports: string[];
  started: string;
  finished: string | null;
}

export interface JobResult {
  job: Job;
}

export interface JobList {
  jobs: Job[];
}

export interface Session {
  id: string;
  name: string;
  profile: string;
  cvs: string[];
  created_at: string;
}

export interface SessionList {
  sessions: Session[];
}

export interface ReportList {
  reports: string[];
}

export interface Report {
  name: string;
  content: string;
}

export interface Candidate {
  name: string;
  file: string;
  score: number | null;
  giudizio: string | null;
  esperienza: string | null;
  fit: string | null;
}

export interface CandidateList {
  candidates: Candidate[];
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  readonly base = this.apiBase();

  constructor(private http: HttpClient) {}

  private apiBase(): string {
    const host = window.location.hostname;
    if (host === 'localhost' || host === '127.0.0.1') {
      return 'http://127.0.0.1:8000';
    }
    return '';
  }

  listCvs(): Observable<CvList> {
    return this.http.get<CvList>(`${this.base}/api/cvs`);
  }

  upload(files: File[]): Observable<UploadResult> {
    const form = new FormData();
    for (const f of files) {
      form.append('files', f, f.name);
    }
    return this.http.post<UploadResult>(`${this.base}/api/cvs/upload`, form);
  }

  deleteCv(name: string): Observable<object> {
    return this.http.delete(`${this.base}/api/cvs/${encodeURIComponent(name)}`);
  }

  exportCvsUrl(): string {
    return `${this.base}/api/cvs/export`;
  }

  deleteAllCvs(): Observable<{ deleted: string[]; count: number }> {
    return this.http.delete<{ deleted: string[]; count: number }>(`${this.base}/api/cvs/all`);
  }

  listJobs(): Observable<JobList> {
    return this.http.get<JobList>(`${this.base}/api/jobs`);
  }

  startJob(profile: string, sessionId?: string, cvs?: string[]): Observable<JobResult> {
    const body: { profile: string; session_id?: string; cvs?: string[] } = { profile };
    if (sessionId) body.session_id = sessionId;
    if (cvs) body.cvs = cvs;
    return this.http.post<JobResult>(`${this.base}/api/jobs`, body);
  }

  getJob(id: string): Observable<JobResult> {
    return this.http.get<JobResult>(`${this.base}/api/jobs/${id}`);
  }

  listSessions(): Observable<SessionList> {
    return this.http.get<SessionList>(`${this.base}/api/sessions`);
  }

  createSession(name: string, profile: string, cvs: string[]): Observable<Session> {
    return this.http.post<Session>(`${this.base}/api/sessions`, { name, profile, cvs });
  }

  deleteSession(id: string): Observable<{ ok: boolean }> {
    return this.http.delete<{ ok: boolean }>(`${this.base}/api/sessions/${encodeURIComponent(id)}`);
  }

  listReports(session?: string): Observable<ReportList> {
    const q = session ? `?session=${encodeURIComponent(session)}` : '';
    return this.http.get<ReportList>(`${this.base}/api/reports${q}`);
  }

  getReport(name: string, session?: string): Observable<Report> {
    const q = session ? `?session=${encodeURIComponent(session)}` : '';
    return this.http.get<Report>(`${this.base}/api/reports/${encodeURIComponent(name)}${q}`);
  }

  listCandidates(session?: string): Observable<CandidateList> {
    const q = session ? `?session=${encodeURIComponent(session)}` : '';
    return this.http.get<CandidateList>(`${this.base}/api/reports/summary${q}`);
  }

  reportPdfUrl(name: string, session?: string): string {
    const q = session ? `?session=${encodeURIComponent(session)}` : '';
    return `${this.base}/api/reports/${encodeURIComponent(name)}/pdf${q}`;
  }

  indeedLaunch(): Observable<{ ok: boolean; message: string }> {
    return this.http.post<{ ok: boolean; message: string }>(`${this.base}/api/indeed/launch`, null);
  }

  indeedSync(): Observable<{ copied: string[]; count: number; cvs: string[] }> {
    return this.http.post<{ copied: string[]; count: number; cvs: string[] }>(`${this.base}/api/indeed/sync`, null);
  }

  indeedArchive(): Observable<{ count: number; available: boolean }> {
    return this.http.get<{ count: number; available: boolean }>(`${this.base}/api/indeed/downloads`);
  }

  indeedClear(): Observable<{ deleted: number; count: number }> {
    return this.http.delete<{ deleted: number; count: number }>(`${this.base}/api/indeed/downloads`);
  }

  listProfiles(): Observable<{ profiles: ProfileTemplate[] }> {
    return this.http.get<{ profiles: ProfileTemplate[] }>(`${this.base}/api/profiles`);
  }

  saveProfile(name: string, profile: string): Observable<ProfileTemplate> {
    return this.http.post<ProfileTemplate>(`${this.base}/api/profiles`, { name, profile });
  }

  deleteProfile(pid: string): Observable<{ ok: boolean }> {
    return this.http.delete<{ ok: boolean }>(`${this.base}/api/profiles/${pid}`);
  }
}

export interface ProfileTemplate {
  id: string;
  name: string;
  profile: string;
}