function readTextContent(content) {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content.map((part) => typeof part === 'string' ? part : part?.text ?? '').join('');
  }
  return String(content ?? '');
}

function readUsage(response) {
  const usage = response?.usage_metadata ?? response?.response_metadata?.tokenUsage ?? null;
  if (!usage) return null;
  const inputTokens = usage.input_tokens ?? usage.promptTokens ?? usage.prompt_tokens;
  const outputTokens = usage.output_tokens ?? usage.completionTokens ?? usage.completion_tokens;
  if (!Number.isFinite(inputTokens) || !Number.isFinite(outputTokens)) return null;
  return { inputTokens, outputTokens };
}

export class LangChainModelAdapter {
  constructor({ model }) {
    if (!model || typeof model.invoke !== 'function') {
      throw new TypeError('LangChain model은 invoke 함수를 제공해야 합니다.');
    }
    this.model = model;
  }

  async generate({ system, question, evidence = [], maxOutputChars = 800 }) {
    const evidenceText = evidence.length > 0 ? evidence.join('\n') : '근거 없음';
    let response;
    try {
      response = await this.model.invoke([
        { role: 'system', content: system },
        { role: 'user', content: `질문: ${question}\n근거:\n${evidenceText}` },
      ]);
    } catch (error) {
      if (error instanceof AppError) throw error;
      throw new AppError('MODEL_UNAVAILABLE', 'LLM 모델이 요청을 처리하지 못했습니다.', 503);
    }
    return {
      answer: readTextContent(response?.content).slice(0, maxOutputChars),
      usage: readUsage(response),
    };
  }
}
import { AppError } from './errors.js';
