using System.Collections;
using System.Collections.Generic;
using System.IO;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;
using Vrar.Environment;

namespace Vrar.Tests
{
    /// <summary>
    /// Regression guard for the pasture.
    ///
    /// Livestock used to be dropped into a cluster an order of magnitude tighter
    /// than its own footprints and then left to wander a shared 90 m home radius,
    /// so herds walked through one another and through the conifers. Both are
    /// visual "the scene is broken" bugs rather than crashes, so nothing else in
    /// the suite catches them.
    /// </summary>
    public class LivestockCrowdTests
    {
        private const string SceneName = "Mvp";

        /// <summary>
        /// Solver residual. The crowd solver projects hard constraints rather than
        /// simulating contact, so a handful of metres of slop between two enormous
        /// animals is a pass; a herd walked into a tree trunk is not.
        /// </summary>
        private const float Tolerance = 0.02f;

        private List<Animal> _herd;

        [UnityTest]
        public IEnumerator HerdMembersNeverOverlapEachOther()
        {
            yield return SettledHerd();

            List<Animal> herd = _herd;

            Assert.That(herd.Count, Is.GreaterThanOrEqualTo(20),
                "the pasture should still be stocked after the packing rework");

            for (int i = 0; i < herd.Count; i++)
            {
                for (int j = i + 1; j < herd.Count; j++)
                {
                    float gap = Overlap(herd[i], herd[j].transform.position, herd[j].Footprint);
                    Assert.That(gap, Is.LessThanOrEqualTo(Tolerance),
                        $"{herd[i].name} and {herd[j].name} are interpenetrating by {gap:P1}");
                }
            }
        }

        [UnityTest]
        public IEnumerator HerdMembersNeverStandInsideAConifer()
        {
            yield return SettledHerd();

            List<Animal> herd = _herd;

            Assert.That(ObstacleField.Count, Is.GreaterThan(100),
                "the prop footprints must survive into the scene, or nothing is being checked");

            for (int i = 0; i < herd.Count; i++)
            {
                for (int p = 0; p < ObstacleField.Count; p++)
                {
                    if (!ObstacleField.Touching(herd[i].transform.position, herd[i].Footprint, p))
                    {
                        continue;
                    }

                    // Touching reports the raw overlap; allow only the solver residual.
                    Vector3 offset = herd[i].transform.position - ObstacleField.Position(p);
                    offset.y = 0f;
                    float reach = herd[i].Footprint + ObstacleField.Radius(p);
                    float overlap = reach - offset.magnitude;

                    Assert.That(overlap / reach, Is.LessThanOrEqualTo(Tolerance),
                        $"{herd[i].name} is standing {overlap:0.0} m inside a conifer or boulder");
                }
            }
        }

        /// <summary>Load the scene, let the herd walk into the problem, then settle it.</summary>
        private IEnumerator SettledHerd()
        {
            string path = Path.Combine(Application.dataPath, "Scenes/Mvp/Mvp.unity");
            Assert.That(File.Exists(path), Is.True, $"missing {path}; run VRAR/PoC/Build MVP Scene");

            yield return SceneManager.LoadSceneAsync(SceneName, LoadSceneMode.Single);
            yield return null;

            foreach (Vrar.Bootstrap.MvpBootstrap bootstrap in
                     Object.FindObjectsByType<Vrar.Bootstrap.MvpBootstrap>())
            {
                Object.Destroy(bootstrap.gameObject);
            }

            _herd = new List<Animal>(Object.FindObjectsByType<Animal>(FindObjectsSortMode.None));

            // Long enough for a full graze-walk-graze cycle, so the solver is judged
            // on moving animals rather than on the positions the scene baked.
            for (int frame = 0; frame < 300; frame++)
            {
                yield return null;
            }

            yield return null;
        }

        /// <summary>How far two solid discs interpenetrate. Zero or less is clear.</summary>
        private static float Overlap(Animal a, Vector3 otherPosition, float otherRadius)
        {
            Vector3 offset = a.transform.position - otherPosition;
            offset.y = 0f;
            float reach = a.Footprint + otherRadius;
            return (reach - offset.magnitude) / reach;
        }
    }
}