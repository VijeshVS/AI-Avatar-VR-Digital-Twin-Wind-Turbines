using System.IO;
using NUnit.Framework;
using UnityEngine;
using Vrar.Telemetry;

namespace Vrar.Tests
{
    /// <summary>
    /// Contract tests against the payload the Python service really produced
    /// (<c>uv run python -m telemetry.export_sample</c>). If the service changes
    /// shape, these fail before anyone opens the Editor.
    /// </summary>
    public class TelemetryContractTests
    {
        private static readonly string[] ComponentIds =
            { "blade_set", "main_bearing", "gearbox", "generator", "pitch_system" };

        private static readonly string[] RequiredSignals =
        {
            "rotor_angle_deg", "pitch_angle_deg", "rotor_imbalance_index",
            "nacelle_vibration_mm_s", "gearbox_vibration_mm_s",
            "generator_winding_temp_c", "pitch_position_error_deg"
        };

        private TelemetryFrame[] _frames;

        [OneTimeSetUp]
        public void LoadSamples()
        {
            string path = Path.Combine(Application.streamingAssetsPath, "telemetry_sample.json");
            Assert.That(File.Exists(path), Is.True, $"missing {path}; run `uv run python -m telemetry.export_sample`");

            _frames = SampleFrames.Parse(File.ReadAllText(path));
            Assert.That(_frames, Is.Not.Null.And.Not.Empty);
        }

        [Test]
        public void SampleFileCarriesTheExpectedScenario()
        {
            Assert.That(_frames.Length, Is.GreaterThanOrEqualTo(3));
            foreach (TelemetryFrame frame in _frames)
            {
                Assert.That(frame.schema_version, Is.EqualTo(1));
                Assert.That(frame.scenario, Is.EqualTo("gearbox_degradation"));
                Assert.That(frame.healthy_asset, Is.False);
            }
        }

        [Test]
        public void EnvironmentSignalsArePresentAndPlausible()
        {
            foreach (TelemetryFrame frame in _frames)
            {
                Assert.That(frame.environment, Is.Not.Null);
                Assert.That(frame.environment.wind_speed_ms, Is.InRange(3f, 25f));
                Assert.That(frame.environment.rotor_rpm, Is.InRange(0f, 20f));
                Assert.That(frame.environment.active_power_kw, Is.InRange(0f, 4000f));
            }
        }

        [Test]
        public void EveryComponentIsScoredAndExplained()
        {
            foreach (TelemetryFrame frame in _frames)
            {
                Assert.That(frame.components, Has.Length.EqualTo(ComponentIds.Length));

                foreach (string id in ComponentIds)
                {
                    ComponentPayload component = frame.Component(id);
                    Assert.That(component, Is.Not.Null, $"payload is missing component '{id}'");
                    Assert.That(component.health, Is.InRange(0f, 1f));
                    Assert.That(component.state, Is.EqualTo("healthy").Or.EqualTo("warning").Or.EqualTo("critical"));
                    Assert.That(component.factors, Is.Not.Null);
                    Assert.That(component.factors.Length, Is.LessThanOrEqualTo(3));

                    foreach (FactorPayload factor in component.factors)
                    {
                        Assert.That(factor.signal, Is.Not.Empty);
                        Assert.That(factor.severity, Is.InRange(0f, 1f));
                        Assert.That(factor.unit, Is.Not.Null);
                    }
                }
            }
        }

        [Test]
        public void SignalsCoverEverythingTheRigNeeds()
        {
            foreach (TelemetryFrame frame in _frames)
            {
                foreach (string id in RequiredSignals)
                {
                    Assert.That(frame.Component("gearbox"), Is.Not.Null);
                    bool found = false;
                    foreach (SignalPayload signal in frame.signals)
                    {
                        found |= signal.id == id;
                    }

                    Assert.That(found, Is.True, $"payload is missing signal '{id}'");
                }
            }
        }

        [Test]
        public void FaultProgressionIsVisibleAcrossTheSamples()
        {
            TelemetryFrame first = _frames[0];
            TelemetryFrame last = _frames[_frames.Length - 1];

            Assert.That(first.Component("gearbox").health, Is.GreaterThan(0.9f),
                "the first sample should be a healthy machine");
            Assert.That(last.Component("gearbox").health, Is.LessThan(first.Component("gearbox").health - 0.4f),
                "the gearbox must degrade across the samples");

            Assert.That(last.Component("gearbox").state, Is.EqualTo("critical"));
            Assert.That(last.Component("generator").state, Is.EqualTo("healthy"),
                "the fault must be localised, not plant-wide");
            Assert.That(last.Component("gearbox").PrimaryReason(), Does.Contain("gearbox"));
        }

        [Test]
        public void RotorAngleIsAbsoluteAndMovesBetweenSamples()
        {
            foreach (TelemetryFrame frame in _frames)
            {
                Assert.That(frame.Signal("rotor_angle_deg"), Is.InRange(0f, 360f));
            }

            Assert.That(_frames[1].Signal("rotor_angle_deg"), Is.Not.EqualTo(_frames[0].Signal("rotor_angle_deg")));
        }

        [Test]
        public void UnknownComponentLookupReturnsNullRatherThanThrowing()
        {
            Assert.That(_frames[0].Component("reactor"), Is.Null);
        }
    }
}