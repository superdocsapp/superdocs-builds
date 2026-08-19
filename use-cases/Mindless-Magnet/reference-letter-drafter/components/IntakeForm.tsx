"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import type { EvidenceItem, Intake, Purpose, StrengthBand } from "@/lib/types";

const STRENGTH_OPTIONS: { value: StrengthBand; label: string; hint: string }[] = [
  { value: "strong", label: "Strong", hint: "Confident, unreserved endorsement" },
  { value: "solid", label: "Solid", hint: "Positive but measured, competent and reliable" },
  { value: "mixed", label: "Mixed", hint: "Real strengths and real reservations, side by side" },
  { value: "reluctant", label: "Reluctant / Lukewarm", hint: "Honest but unenthusiastic — reads as lukewarm" },
];

const PURPOSE_OPTIONS: { value: Purpose; label: string }[] = [
  { value: "graduate_school", label: "Graduate school admission" },
  { value: "job", label: "Job application" },
  { value: "fellowship_or_award", label: "Fellowship or award" },
  { value: "other", label: "Other" },
];

function emptyEvidence(): EvidenceItem {
  return { claim: "", evidence: "" };
}

export function IntakeForm({
  onSubmit,
  disabled = false,
}: {
  onSubmit: (intake: Intake) => void;
  disabled?: boolean;
}) {
  const [writerName, setWriterName] = useState("");
  const [writerEmail, setWriterEmail] = useState("");
  const [writerRole, setWriterRole] = useState("");
  const [subjectName, setSubjectName] = useState("");
  const [subjectRole, setSubjectRole] = useState("");
  const [relationship, setRelationship] = useState("");
  const [relationshipDurationMonths, setRelationshipDurationMonths] = useState(6);
  const [purpose, setPurpose] = useState<Purpose>("job");
  const [purposeOther, setPurposeOther] = useState("");
  const [strengthBand, setStrengthBand] = useState<StrengthBand>("solid");
  const [evidence, setEvidence] = useState<EvidenceItem[]>([emptyEvidence()]);
  const [reservations, setReservations] = useState("");
  const [toneNotes, setToneNotes] = useState("");
  const [lengthPreference, setLengthPreference] = useState<Intake["lengthPreference"]>("standard");

  const canSubmit =
    writerName.trim() && subjectName.trim() && relationship.trim() && evidence.some((e) => e.claim.trim());

  function updateEvidence(index: number, field: keyof EvidenceItem, value: string) {
    setEvidence((prev) => prev.map((item, i) => (i === index ? { ...item, [field]: value } : item)));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit({
      writerName,
      writerEmail,
      writerRole,
      subjectName,
      subjectRole,
      relationship,
      relationshipDurationMonths,
      purpose,
      purposeOther: purpose === "other" ? purposeOther : undefined,
      strengthBand,
      evidence,
      reservations,
      toneNotes: toneNotes || undefined,
      lengthPreference,
    });
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Writer</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="writerName">Your name</Label>
            <Input id="writerName" value={writerName} onChange={(e) => setWriterName(e.target.value)} required />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="writerEmail">Your email (used to keep your voice consistent across letters)</Label>
            <Input
              id="writerEmail"
              type="email"
              value={writerEmail}
              onChange={(e) => setWriterEmail(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2 sm:col-span-2">
            <Label htmlFor="writerRole">Your role / title</Label>
            <Input id="writerRole" value={writerRole} onChange={(e) => setWriterRole(e.target.value)} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Subject</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="subjectName">Their name</Label>
            <Input id="subjectName" value={subjectName} onChange={(e) => setSubjectName(e.target.value)} required />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="subjectRole">Their role</Label>
            <Input id="subjectRole" value={subjectRole} onChange={(e) => setSubjectRole(e.target.value)} />
          </div>
          <div className="flex flex-col gap-2 sm:col-span-2">
            <Label htmlFor="relationship">Your relationship to them</Label>
            <Input
              id="relationship"
              placeholder="e.g. direct manager, thesis advisor"
              value={relationship}
              onChange={(e) => setRelationship(e.target.value)}
              required
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="duration">Months you&apos;ve known them</Label>
            <Input
              id="duration"
              type="number"
              min={0}
              value={relationshipDurationMonths}
              onChange={(e) => setRelationshipDurationMonths(Number(e.target.value))}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label>Purpose</Label>
            <Select value={purpose} onValueChange={(v) => setPurpose(v as Purpose)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PURPOSE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {purpose === "other" && (
            <div className="flex flex-col gap-2 sm:col-span-2">
              <Label htmlFor="purposeOther">Describe the purpose</Label>
              <Input id="purposeOther" value={purposeOther} onChange={(e) => setPurposeOther(e.target.value)} />
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Strength — calibrate honestly</CardTitle>
        </CardHeader>
        <CardContent>
          <RadioGroup
            value={strengthBand}
            onValueChange={(v) => setStrengthBand(v as StrengthBand)}
            className="grid gap-3 sm:grid-cols-2"
          >
            {STRENGTH_OPTIONS.map((opt) => (
              <Label
                key={opt.value}
                htmlFor={`strength-${opt.value}`}
                className="flex cursor-pointer items-start gap-3 rounded-md border p-3 has-[[data-state=checked]]:border-primary"
              >
                <RadioGroupItem id={`strength-${opt.value}`} value={opt.value} className="mt-1" />
                <span className="flex flex-col gap-0.5">
                  <span className="font-medium">{opt.label}</span>
                  <span className="text-muted-foreground text-sm">{opt.hint}</span>
                </span>
              </Label>
            ))}
          </RadioGroup>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Claims and evidence</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {evidence.map((item, i) => (
            <div key={i} className="grid gap-3 rounded-md border p-3 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <Label htmlFor={`claim-${i}`}>Claim</Label>
                <Input
                  id={`claim-${i}`}
                  placeholder="e.g. Reliable under deadline pressure"
                  value={item.claim}
                  onChange={(e) => updateEvidence(i, "claim", e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor={`evidence-${i}`}>Supporting evidence</Label>
                <Input
                  id={`evidence-${i}`}
                  placeholder="e.g. Delivered the Q3 migration a week early"
                  value={item.evidence}
                  onChange={(e) => updateEvidence(i, "evidence", e.target.value)}
                />
              </div>
            </div>
          ))}
          <Button
            type="button"
            variant="outline"
            onClick={() => setEvidence((prev) => [...prev, emptyEvidence()])}
          >
            Add another claim
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Reservations</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="reservations">
              Anything you&apos;re holding back on, or would want a reader to know? Leave blank if none.
            </Label>
            <Textarea
              id="reservations"
              rows={3}
              value={reservations}
              onChange={(e) => setReservations(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="toneNotes">Tone notes (optional)</Label>
            <Textarea id="toneNotes" rows={2} value={toneNotes} onChange={(e) => setToneNotes(e.target.value)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label>Length</Label>
            <Select
              value={lengthPreference}
              onValueChange={(v) => setLengthPreference(v as Intake["lengthPreference"])}
            >
              <SelectTrigger className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="brief">Brief</SelectItem>
                <SelectItem value="standard">Standard</SelectItem>
                <SelectItem value="detailed">Detailed</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <Button type="submit" size="lg" disabled={!canSubmit || disabled}>
        Draft letter
      </Button>
    </form>
  );
}
