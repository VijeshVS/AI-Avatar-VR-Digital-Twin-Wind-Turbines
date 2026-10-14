using System.Collections;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using Vrar.Telemetry;
using Vrar.Turbine;

namespace Vrar.Tests
{
    /// <summary>
    /// Live round trip against the FastAPI service. Skipped when the service is
    /// not running, so the suite still passes offline:
    ///
    ///   cd tools/telemetry &amp;&amp; uv run uvicorn telemetry.main:app --port 8000
    ///   unity test --mode PlayMode --filter LiveService
    /// </summary>
    public class LiveServiceTests
    {
        private const string Endpoint = "http://127.0.0.1:8000";
        private static readonly int TimeoutSeconds = 120;

        [UnityTest]
        public IEnumerator LiveFrameDrivesTheRig()
        {
            TelemetryFrame frame = null;
            string error = null;
            var source = new HttpTelemetrySource(Endpoint, 3);

            yield return source.Fetch(120, (received, failure) =>
            {
                frame = received;
                error = failure;
            });

            if (frame == null)
            {
                Assert.Ignore($"telemetry service not reachable at {Endpoint} ({error})");
            }

            Assert.That(frame.components, Has.Length.EqualTo(5));
            Assert.That(frame.Signal("rotor_angle_deg"), Is.InRange(0f, 360f));

            GameObject host = new GameObject("LiveRig");
            try
            {
                TurbineRig rig = TurbineFactory.Build();
                rig.transform.SetParent(host.transform, false);
                rig.Apply(frame);

                // At t=120 s in gearbox_degradation the gearbox must be failing.
                Avatar.ComponentAvatar gearbox = rig.Avatar("gearbox");
                Assert.That(gearbox.Health, Is.EqualTo(frame.Component("gearbox").health).Within(1e-4f));
                Assert.That(rig.WorstHealth(), Is.LessThanOrEqualTo(frame.WorstHealth() + 1e-4f));
            }
            finally
            {
                Object.Destroy(host);
            }
        }
    }
}