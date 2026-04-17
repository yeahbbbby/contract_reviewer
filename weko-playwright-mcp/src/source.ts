import fs from 'node:fs/promises';
import path from 'node:path';
import { writeDocxFile } from './docx.js';

export type SourceKind = 'auto' | 'pdf' | 'image' | 'text';

export type SourceExtractionResult = {
  sourceKind: Exclude<SourceKind, 'auto'>;
  markdown: string;
  warnings: string[];
};

function detectSourceKind(filePath: string): Exclude<SourceKind, 'auto'> {
  const extension = path.extname(filePath).toLowerCase();
  if (extension === '.pdf') {
    return 'pdf';
  }
  if (['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'].includes(extension)) {
    return 'image';
  }
  return 'text';
}

async function extractPdfText(filePath: string) {
  const pdfParseModule = await import('pdf-parse');
  const pdfParse = ((pdfParseModule as any).default ?? pdfParseModule) as (data: Buffer) => Promise<{ text: string }>;
  const buffer = await fs.readFile(filePath);
  const data = await pdfParse(buffer);
  return data.text ?? '';
}

async function extractImageText(filePath: string) {
  const tesseractModule = await import('tesseract.js');
  const createWorker = (tesseractModule as any).createWorker ?? (tesseractModule as any).default?.createWorker;
  if (!createWorker) {
    throw new Error('Tesseract OCR worker is not available.');
  }

  const worker = await createWorker('chi_sim+eng');
  try {
    const result = await worker.recognize(filePath);
    return result?.data?.text ?? '';
  } finally {
    await worker.terminate().catch(() => undefined);
  }
}

function normalizeText(text: string) {
  return text
    .replace(/\u00a0/g, ' ')
    .replace(/\r\n/g, '\n')
    .replace(/[\t ]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

export async function extractSourceMarkdown(input: {
  sourcePath: string;
  sourceKind?: SourceKind;
}) : Promise<SourceExtractionResult> {
  const kind = input.sourceKind && input.sourceKind !== 'auto' ? input.sourceKind : detectSourceKind(input.sourcePath);
  const warnings: string[] = [];

  if (kind === 'text') {
    const raw = await fs.readFile(input.sourcePath, 'utf8');
    return {
      sourceKind: kind,
      markdown: normalizeText(raw),
      warnings,
    };
  }

  if (kind === 'pdf') {
    try {
      const text = normalizeText(await extractPdfText(input.sourcePath));
      if (!text) {
        warnings.push('PDF text extraction returned empty content. Trying OCR fallback for scanned PDF.');
        const ocrText = normalizeText(await extractImageText(input.sourcePath).catch(() => ''));
        if (ocrText) {
          return {
            sourceKind: kind,
            markdown: ocrText,
            warnings,
          };
        }
        warnings.push('OCR fallback also returned empty content. Please check whether the PDF is image-based or too blurry.');
      }
      return {
        sourceKind: kind,
        markdown: text,
        warnings,
      };
    } catch (error) {
      warnings.push(`PDF text extraction failed: ${(error as Error).message}`);
      throw new Error(`Unable to extract text from PDF: ${(error as Error).message}`);
    }
  }

  if (kind === 'image') {
    try {
      const text = normalizeText(await extractImageText(input.sourcePath));
      if (!text) {
        warnings.push('OCR returned empty content. Please check whether the image is clear enough for OCR.');
      }
      return {
        sourceKind: kind,
        markdown: text,
        warnings,
      };
    } catch (error) {
      throw new Error(`Unable to OCR image: ${(error as Error).message}`);
    }
  }

  throw new Error(`Unsupported source kind: ${kind}`);
}

export async function prepareSourceDocx(input: {
  sourcePath: string;
  title: string;
  sourceKind?: SourceKind;
  normalizedDocxPath: string;
}) {
  const extraction = await extractSourceMarkdown({
    sourcePath: input.sourcePath,
    sourceKind: input.sourceKind,
  });

  await writeDocxFile({
    filePath: input.normalizedDocxPath,
    title: input.title,
    bodyMarkdown: extraction.markdown,
  });

  return {
    ...extraction,
    normalizedDocxPath: input.normalizedDocxPath,
  };
}