"use client";

import React from "react";
import { ButtonVariantEnum } from "@/shared/enums";
import { Button } from "@/shared/presentation/components/Button";
import {
  APPROVAL_MODES,
  CATEGORIES,
  ONBOARDING_AGENTS,
  ONBOARDING_LABELS,
  USE_CASES,
} from "../../constants";
import { ApprovalModeEnum, OnboardingStepEnum } from "../../enums";
import { useOnboardingForm } from "../../hooks/useOnboardingForm";
import { AuthChip } from "../components/AuthChip";
import { AuthField } from "../components/AuthField";
import { AuthFrame } from "../components/AuthFrame";
import { AuthOptionCard } from "../components/AuthOptionCard";

export function OnboardingPage() {
  const {
    currentStep,
    currency,
    useCase,
    setUseCase,
    categories,
    handleCategoryToggle,
    monthlyBudget,
    handleBudgetChange,
    approvalMode,
    setApprovalMode,
    approvalLimit,
    handleLimitChange,
    selectedAgents,
    handleAgentToggle,
    referralSource,
    setReferralSource,
    isSubmitting,
    errorMessage,
    canProceed,
    goToPreviousStep,
    handleNextOrSubmit,
  } = useOnboardingForm();

  const isStepZero = currentStep === OnboardingStepEnum.UseCase;
  const isStepOne = currentStep === OnboardingStepEnum.Categories;
  const isStepTwo = currentStep === OnboardingStepEnum.Approval;

  const isAboveLimitApproval = approvalMode === ApprovalModeEnum.AboveLimit;
  const isPreviousAllowed = currentStep > OnboardingStepEnum.UseCase;
  const hasError = Boolean(errorMessage);

  const stepProgress = {
    current: currentStep + 2,
    total: 4,
    label: ONBOARDING_LABELS[currentStep] || "Onboarding",
  };

  const nextButtonLabel = isStepTwo
    ? isSubmitting
      ? "Finishing…"
      : "Finish setup"
    : "Continue";

  return (
    <AuthFrame step={stepProgress} showSignOut={true} wide={true}>
      <form onSubmit={handleNextOrSubmit} className="space-y-6">
        {isStepZero ? (
          <>
            <div className="space-y-1.5">
              <h1 className="text-2xl font-semibold tracking-tight">What brings you to Sepilo?</h1>
              <p className="text-sm text-fg-muted">We&apos;ll set up your checks around how your agents shop.</p>
            </div>
            <div className="grid gap-2.5">
              {USE_CASES.map((u) => (
                <AuthOptionCard
                  key={u.id}
                  selected={useCase === u.id}
                  onClick={() => setUseCase(u.id)}
                  title={u.title}
                  description={u.description}
                />
              ))}
            </div>
          </>
        ) : null}

        {isStepOne ? (
          <>
            <div className="space-y-1.5">
              <h1 className="text-2xl font-semibold tracking-tight">What will your agents buy?</h1>
              <p className="text-sm text-fg-muted">Purchases outside these categories will be held for you.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {CATEGORIES.map((c) => (
                <AuthChip
                  key={c.id}
                  label={c.label}
                  selected={categories.includes(c.id)}
                  onClick={() => handleCategoryToggle(c.id)}
                />
              ))}
            </div>
            <AuthField
              label="Monthly spending limit for agents"
              hint="You can change this later in your mandates."
            >
              <div className="relative">
                <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-xs font-medium text-fg-dim">
                  {currency}
                </span>
                <input
                  inputMode="numeric"
                  value={monthlyBudget}
                  onChange={(e) => handleBudgetChange(e.target.value)}
                  className="saas-input h-11 rounded-xl pl-14! pr-3.5!"
                  placeholder="500"
                />
              </div>
            </AuthField>
          </>
        ) : null}

        {isStepTwo ? (
          <>
            <div className="space-y-1.5">
              <h1 className="text-2xl font-semibold tracking-tight">When should we ask you?</h1>
              <p className="text-sm text-fg-muted">
                Sepilo always blocks hidden instructions and wrong items. This sets when you approve.
              </p>
            </div>
            <div className="grid gap-2.5">
              {APPROVAL_MODES.map((a) => (
                <AuthOptionCard
                  key={a.id}
                  selected={approvalMode === a.id}
                  onClick={() => setApprovalMode(a.id)}
                  title={a.title}
                  description={a.description}
                />
              ))}
            </div>

            {isAboveLimitApproval ? (
              <AuthField label="Ask me for orders above" hint={null}>
                <div className="relative">
                  <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-xs font-medium text-fg-dim">
                    {currency}
                  </span>
                  <input
                    inputMode="numeric"
                    value={approvalLimit}
                    onChange={(e) => handleLimitChange(e.target.value)}
                    className="saas-input h-11 rounded-xl pl-14! pr-3.5!"
                    placeholder="50"
                  />
                </div>
              </AuthField>
            ) : null}

            <div className="space-y-2">
              <span className="block text-[13px] font-medium text-fg-2">Which assistants will shop for you?</span>
              <div className="flex flex-wrap gap-2">
                {ONBOARDING_AGENTS.map((agent) => (
                  <AuthChip
                    key={agent.id}
                    label={agent.label}
                    selected={selectedAgents.includes(agent.id)}
                    onClick={() => handleAgentToggle(agent.id)}
                  />
                ))}
              </div>
            </div>

            <AuthField label="How did you hear about us?" hint="Optional.">
              <input
                maxLength={120}
                value={referralSource}
                onChange={(e) => setReferralSource(e.target.value)}
                className="saas-input h-11 rounded-xl px-3.5!"
                placeholder="Twitter, GitHub, friend..."
              />
            </AuthField>
          </>
        ) : null}

        {hasError ? (
          <p role="alert" className="text-[13px] text-rose-400">
            {errorMessage}
          </p>
        ) : null}

        <div className="flex items-center gap-3">
          {isPreviousAllowed ? (
            <Button
              type="button"
              variant={ButtonVariantEnum.Outline}
              onClick={goToPreviousStep}
              className="h-11 px-5"
            >
              Back
            </Button>
          ) : null}

          <Button
            type="submit"
            variant={ButtonVariantEnum.Primary}
            disabled={!canProceed || isSubmitting}
            isLoading={isSubmitting}
            className="h-11 flex-1"
          >
            {nextButtonLabel}
          </Button>
        </div>
      </form>
    </AuthFrame>
  );
}
