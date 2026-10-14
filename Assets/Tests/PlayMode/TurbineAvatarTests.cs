using System.Collections;
using System.Collections.Generic;
using System.IO;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using Vrar.Avatar;
using Vrar.Health;
using Vrar.Telemetry;
using Vrar.Turbine;

namespace Vrar.Tests
{
    /// <summary>
    /// The core claim of the PoC: a telemetry frame visibly changes the machine.
    /// These tests assert that chain end to end - frame in, avatar out.
    /// </summary>
    public class TurbineAvatarTests
    {
        private GameObject _root;
        private TurbineRig _rig;
        private TelemetryFrame[] _frames;

        [SetUp]
        public void SetUp()
        {
            string path = Path.Combine(Application.streamingAssetsPath, "telemetry_sample.json");
            Assert.That(File.Exists(path), Is.True, $"missing {path}; run `uv run python -m telemetry.export_sample`");

            _frames = SampleFrames.Parse(File.ReadAllText(path));
            _root = new GameObject("TestRig");
            _rig = TurbineFactory.Build();
            _rig.transform.SetParent(_root.transform, false);
        }

        [TearDown]
        public void TearDown()
        {
            Object.DestroyImmediate(_root);
        }

        private TelemetryFrame Last => _frames[_frames.Length - 1];

        [Test]
        public void FactoryBuildsTheWholeMachine()
        {
            Assert.That(_rig.Avatars.Count, Is.EqualTo(5));
            Assert.That(_rig.transform.Find("Tower"), Is.Not.Null);
            Assert.That(_rig.transform.Find("Nacelle"), Is.Not.Null);

            foreach (string id in new[] { "blade_set", "main_bearing", "gearbox", "generator", "pitch_system" })
            {
                Assert.That(_rig.Avatar(id), Is.Not.Null, $"no avatar for '{id}'");
            }
        }

        [Test]
        public void BladeAvatarOwnsOnlyTheBlades()
        {
            Avatar.ComponentAvatar blades = _rig.Avatar("blade_set");
            Assert.That(blades.GetComponentsInChildren<Renderer>(true).Length, Is.EqualTo(TurbineFactory.BladeCount));

            Avatar.ComponentAvatar generator = _rig.Avatar("generator");
            Assert.That(generator.GetComponentsInChildren<Renderer>(true).Length, Is.EqualTo(1));
        }

        [UnityTest]
        public IEnumerator PrimitivesAreColliderFreeSoTremorDoesNotFightPhysics()
        {
            yield return null;

            foreach (Collider collider in _root.GetComponentsInChildren<Collider>())
            {
                Assert.That(collider, Is.Null);
            }
        }

        [UnityTest]
        public IEnumerator HealthyFrameLeavesEveryAvatarGreen()
        {
            _rig.Apply(_frames[0]);
            yield return null;

            foreach (ComponentAvatar avatar in _rig.Avatars)
            {
                Assert.That(avatar.Health, Is.EqualTo(1f).Within(0.001f));
                Assert.That(avatar.CurrentColor.g, Is.GreaterThan(avatar.CurrentColor.r),
                    $"{avatar.ComponentId} should read green while healthy");
                Assert.That(avatar.CurrentColor.g, Is.GreaterThan(avatar.CurrentColor.b),
                    $"{avatar.ComponentId} should read green while healthy");
            }
        }

        [Test]
        public void FaultedFrameScoresTheGearboxDownAndSparesTheGenerator()
        {
            _rig.Apply(Last);

            Assert.That(_rig.Avatar("gearbox").Health, Is.LessThan(0.5f));
            Assert.That(_rig.Avatar("generator").Health, Is.GreaterThan(0.9f));
            Assert.That(_rig.WorstHealth(), Is.EqualTo(_rig.Avatar("gearbox").Health).Within(0.001f));
        }

        [UnityTest]
        public IEnumerator FaultedFrameTurnsTheGearboxRed()
        {
            _rig.Apply(Last);
            yield return null;

            Color red = _rig.Avatar("gearbox").CurrentColor;
            Color green = _rig.Avatar("generator").CurrentColor;

            Assert.That(red.r, Is.GreaterThan(red.g), "a failing part must read redder than green");
            Assert.That(green.g, Is.GreaterThan(green.r), "a healthy part must read greener than red");
        }

        [Test]
        public void VibrationIsDerivedFromTheRightSignalPerComponent()
        {
            _rig.Apply(Last);

            Assert.That(_rig.Avatar("gearbox").VibrationAmplitude, Is.GreaterThan(1f), "a hot gearbox must be shaking");
            Assert.That(_rig.Avatar("main_bearing").VibrationAmplitude,
                Is.EqualTo(Last.Signal("nacelle_vibration_mm_s")).Within(0.001f));

            _rig.Apply(_frames[0]);
            Assert.That(_rig.Avatar("generator").VibrationAmplitude, Is.EqualTo(0f).Within(0.001f),
                "a cool generator must not tremble");
        }

        [Test]
        public void RotorFollowsTheServiceAzimuth()
        {
            _rig.Apply(_frames[1]);

            Quaternion expected = Quaternion.Euler(0f, _frames[1].environment.yaw_deg, _frames[1].Signal("rotor_angle_deg"));
            Assert.That(Quaternion.Angle(_rig.Rotor.localRotation, expected), Is.LessThan(0.5f));
        }

        [Test]
        public void EachFrameChangesSomethingVisible()
        {
            _rig.Apply(_frames[0]);
            Quaternion before = _rig.Rotor.localRotation;

            _rig.Apply(_frames[1]);
            Assert.That(Quaternion.Angle(before, _rig.Rotor.localRotation), Is.GreaterThan(1f));
        }

        [Test]
        public void RepeatedFramesAreStable()
        {
            _rig.Apply(Last);
            float health = _rig.Avatar("gearbox").Health;
            Quaternion rotor = _rig.Rotor.localRotation;

            _rig.Apply(Last);
            Assert.That(_rig.Avatar("gearbox").Health, Is.EqualTo(health).Within(1e-5f));
            Assert.That(Quaternion.Angle(rotor, _rig.Rotor.localRotation), Is.LessThan(0.01f));
        }

        [Test]
        public void NullFrameIsIgnored()
        {
            _rig.Apply(_frames[0]);
            float health = _rig.Avatar("gearbox").Health;

            _rig.Apply(null);
            Assert.That(_rig.Avatar("gearbox").Health, Is.EqualTo(health).Within(1e-5f));
        }

        [UnityTest]
        public IEnumerator AvatarEmissionActuallyReachesTheRenderer()
        {
            _rig.Apply(Last);
            yield return null;

            Renderer renderer = _rig.Avatar("gearbox").GetComponentInChildren<Renderer>();
            Assert.That(renderer, Is.Not.Null);

            MaterialPropertyBlock block = new MaterialPropertyBlock();
            renderer.GetPropertyBlock(block);
            Color emission = block.GetColor("_EmissionColor");

            Assert.That(emission.maxColorComponent, Is.GreaterThan(0.05f));
            Assert.That(emission.r, Is.GreaterThan(emission.b), "emission should carry the alarm hue");
        }

        [UnityTest]
        public IEnumerator FailingPartsTremorWhileHealthyOnesHoldStill()
        {
            _rig.Apply(Last);
            yield return null;
            yield return null;

            Transform gearbox = _rig.Avatar("gearbox").transform;
            Transform generator = _rig.Avatar("generator").transform;
            Vector3 gearboxRest = gearbox.localPosition;
            Vector3 generatorRest = generator.localPosition;

            float gearboxMotion = 0f;
            float generatorMotion = 0f;
            for (int i = 0; i < 8; i++)
            {
                yield return null;
                gearboxMotion = Mathf.Max(gearboxMotion, Vector3.Distance(gearbox.localPosition, gearboxRest));
                generatorMotion = Mathf.Max(generatorMotion, Vector3.Distance(generator.localPosition, generatorRest));
            }

            Assert.That(gearboxMotion, Is.GreaterThan(0f), "the failing gearbox should visibly shake");
            Assert.That(generatorMotion, Is.EqualTo(0f).Within(1e-6f), "the healthy generator should hold still");
        }

        [Test]
        public void PaletteBandsMatchTheDocumentedThresholds()
        {
            Assert.That(HealthPalette.ColorFor(1f).g, Is.GreaterThan(HealthPalette.ColorFor(1f).r));
            Assert.That(HealthPalette.ColorFor(0.74f).r, Is.GreaterThan(HealthPalette.ColorFor(0.74f).b));
            Assert.That(HealthPalette.ColorFor(0.2f).r, Is.GreaterThan(HealthPalette.ColorFor(0.2f).g));
            Assert.That(HealthPalette.StateFor(0.9f), Is.EqualTo("healthy"));
            Assert.That(HealthPalette.StateFor(0.6f), Is.EqualTo("warning"));
            Assert.That(HealthPalette.StateFor(0.1f), Is.EqualTo("critical"));
            Assert.That(HealthPalette.Distress(1f), Is.EqualTo(0f).Within(1e-6f));
            Assert.That(HealthPalette.Distress(0f), Is.EqualTo(1f).Within(1e-6f));
        }
    }
}