import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
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

export interface ReportList {
  reports: string[];
}

export interface Report {
  name: string;
  content: string;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly base = this.apiBase();

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

  startJob(profile: string): Observable<JobResult> {
    const params = new HttpParams().set('profile', profile);
    return this.http.post<JobResult>(`${this.base}/api/jobs`, null, { params });
  }

  getJob(id: string): Observable<JobResult> {
    return this.http.get<JobResult>(`${this.base}/api/jobs/${id}`);
  }

  listReports(): Observable<ReportList> {
    return this.http.get<ReportList>(`${this.base}/api/reports`);
  }

  getReport(name: string): Observable<Report> {
    return this.http.get<Report>(`${this.base}/api/reports/${encodeURIComponent(name)}`);
  }

  reportPdfUrl(name: string): string {
    return `${this.base}/api/reports/${encodeURIComponent(name)}/pdf`;
  }

  indeedLaunch(): Observable<{ ok: boolean; message: string }> {
    return this.http.post<{ ok: boolean; message: string }>(`${this.base}/api/indeed/launch`, null);
  }

  indeedSync(): Observable<{ copied: string[]; count: number; cvs: string[] }> {
    return this.http.post<{ copied: string[]; count: number; cvs: string[] }>(`${this.base}/api/indeed/sync`, null);
  }
}